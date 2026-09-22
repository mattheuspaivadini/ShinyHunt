#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shiny_core.py
Módulo central para o Shiny Charmander Hunter.
Contém configurações, gerenciador de processos mGBA e servidor TCP de coordenação.
"""

import errno
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional


# Determina o diretório base (se congelado com PyInstaller ou executado como script)
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).parent.resolve()
else:
    SCRIPT_DIR = Path(__file__).parent.resolve()

DEFAULT_LUA_PATH = SCRIPT_DIR / "shiny_hunt.lua"

# Se o script Lua não for encontrado na pasta do .exe, tenta extrair dos arquivos empacotados
if not DEFAULT_LUA_PATH.exists() and hasattr(sys, "_MEIPASS"):
    bundled_lua = Path(sys._MEIPASS) / "shiny_hunt.lua"
    if bundled_lua.exists():
        try:
            shutil.copy2(bundled_lua, DEFAULT_LUA_PATH)
        except Exception:
            DEFAULT_LUA_PATH = bundled_lua

CONFIG_FILE = SCRIPT_DIR / "config.json"


@dataclass
class HuntConfig:
    """Configurações da caçada."""
    mgba_path: str = r"C:\Program Files\mGBA\mGBA.exe"
    rom_path: str = r"C:\roms\FireRed.gba"
    sav_path: str = r"C:\roms\FireRed.sav"
    num_instances: int = 10
    server_port: int = 27015
    lua_script_path: str = str(DEFAULT_LUA_PATH)

    @property
    def instances_dir(self) -> Path:
        """Diretório onde as cópias de instâncias serão armazenadas."""
        rom_p = Path(self.rom_path)
        if rom_p.parent.exists() and os.access(rom_p.parent, os.W_OK):
            return rom_p.parent / "instances"
        return SCRIPT_DIR / "instances"

    def validate(self) -> List[str]:
        """Valida os arquivos necessários e retorna lista de erros (vazia se tudo ok)."""
        errors = []
        if not self.mgba_path or not Path(self.mgba_path).is_file():
            errors.append(f"Executável do mGBA não encontrado: {self.mgba_path}")
        if not self.rom_path or not Path(self.rom_path).is_file():
            errors.append(f"Arquivo da ROM não encontrado: {self.rom_path}")
        if not self.sav_path or not Path(self.sav_path).is_file():
            errors.append(f"Arquivo do Save não encontrado: {self.sav_path}")
        if not self.lua_script_path or not Path(self.lua_script_path).is_file():
            errors.append(f"Script Lua não encontrado: {self.lua_script_path}")
        if self.num_instances < 1 or self.num_instances > 30:
            errors.append("A quantidade de instâncias deve estar entre 1 e 30.")
        if self.server_port < 1024 or self.server_port > 65535:
            errors.append("A porta do servidor deve estar entre 1024 e 65535.")
        return errors

    def save(self, filepath: Optional[Path] = None):
        """Salva a configuração em formato JSON."""
        target = filepath or CONFIG_FILE
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=4)
        except Exception:
            pass

    @classmethod
    def load(cls, filepath: Optional[Path] = None) -> "HuntConfig":
        """Carrega a configuração salva ou usa os valores padrão."""
        target = filepath or CONFIG_FILE
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return cls(
                        mgba_path=data.get("mgba_path", r"C:\Program Files\mGBA\mGBA.exe"),
                        rom_path=data.get("rom_path", r"C:\roms\FireRed.gba"),
                        sav_path=data.get("sav_path", r"C:\roms\FireRed.sav"),
                        num_instances=int(data.get("num_instances", 10)),
                        server_port=int(data.get("server_port", 27015)),
                        lua_script_path=data.get("lua_script_path", str(DEFAULT_LUA_PATH)),
                    )
            except Exception:
                pass
        return cls()


def format_elapsed(start_time: Optional[datetime]) -> str:
    """Formata o tempo decorrido como HH:MM:SS."""
    if not start_time:
        return "00:00:00"
    elapsed = max(0, int((datetime.now() - start_time).total_seconds()))
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def calculate_shiny_chance(total_attempts: int, base_chance: int = 8192) -> float:
    """Calcula a probabilidade acumulada percentual de encontrar ao menos 1 shiny."""
    if total_attempts <= 0:
        return 0.0
    # 1 - ((N - 1) / N) ^ total_attempts
    prob = 1.0 - ((base_chance - 1) / base_chance) ** total_attempts
    return prob * 100.0


class ShinyServer:
    """
    Servidor TCP que coordena as instâncias Lua do mGBA.
    """

    def __init__(
        self,
        port: int = 27015,
        max_instances: int = 15,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ):
        self.port = port
        self.max_instances = max_instances
        self.on_event = on_event
        self.server_socket: Optional[socket.socket] = None
        self.clients: Dict[int, socket.socket] = {}
        self.shiny_found = False
        self.shiny_info: Optional[dict] = None
        self.lock = threading.Lock()
        self.instance_stats: Dict[int, dict] = {}
        self.total_attempts = 0
        self.banked_attempts = 0
        self._next_id = 0
        self.connected_count = 0
        self.start_time: Optional[datetime] = None
        self._running = False

    def _emit(self, event_type: str, data: Optional[dict] = None):
        """Envia evento para callback se registrado."""
        if self.on_event:
            try:
                self.on_event(event_type, data or {})
            except Exception:
                pass

    def start(self):
        """Inicia o servidor TCP em background."""
        self.start_time = datetime.now()
        self._running = True
        self.shiny_found = False
        self.shiny_info = None
        self.total_attempts = 0
        self.banked_attempts = 0
        self.instance_stats.clear()
        self.clients.clear()
        self._next_id = 0
        self.connected_count = 0

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)
        self.server_socket.bind(("127.0.0.1", self.port))
        self.server_socket.listen(self.max_instances + 5)

        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

    def stop(self):
        """Para o servidor e fecha todas as conexões ativas."""
        self._running = False
        with self.lock:
            for conn in list(self.clients.values()):
                try:
                    conn.close()
                except Exception:
                    pass
            self.clients.clear()

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

    def _accept_loop(self):
        """Loop de aceitação de conexões."""
        while self._running and not self.shiny_found:
            try:
                if not self.server_socket:
                    break
                conn, _ = self.server_socket.accept()
                with self.lock:
                    self._next_id += 1
                    client_id = self._next_id
                    self.connected_count += 1
                    self.clients[client_id] = conn
                    self.instance_stats[client_id] = {
                        "attempts": 0,
                        "status": "conectado",
                        "last_update": datetime.now(),
                    }

                # Envia ID para o script Lua
                try:
                    conn.send(f"ID|{client_id}\n".encode("utf-8"))
                except Exception:
                    pass

                self._emit("client_connected", {
                    "client_id": client_id,
                    "connected_count": self.connected_count,
                })

                thread = threading.Thread(
                    target=self._handle_client,
                    args=(conn, client_id),
                    daemon=True,
                )
                thread.start()

            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket, client_id: int):
        """Processa mensagens recebidas de uma instância Lua."""
        buffer = ""
        conn.settimeout(1.0)
        while self._running and not self.shiny_found:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._process_message(line.strip(), client_id)
            except socket.timeout:
                continue
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                break

        # Cliente desconectou
        with self.lock:
            stats = self.instance_stats.get(client_id)
            if stats and stats["status"] != "★ SHINY!":
                self.banked_attempts += stats.get("attempts", 0)
                stats["status"] = "desconectado"
                self.clients.pop(client_id, None)
                self.connected_count = max(0, self.connected_count - 1)
                self.total_attempts = self.banked_attempts + sum(
                    s.get("attempts", 0) for cid, s in self.instance_stats.items()
                    if s.get("status") != "desconectado"
                )

        self._emit("client_disconnected", {
            "client_id": client_id,
            "connected_count": self.connected_count,
            "total_attempts": self.total_attempts,
        })

    def _process_message(self, msg: str, client_id: int):
        """Trata os comandos enviados pelo script Lua."""
        if not msg:
            return

        parts = msg.split("|")
        cmd = parts[0]

        with self.lock:
            if client_id not in self.instance_stats:
                self.instance_stats[client_id] = {
                    "attempts": 0,
                    "status": "conectado",
                    "last_update": datetime.now(),
                }

            stat = self.instance_stats[client_id]
            stat["last_update"] = datetime.now()

            if cmd == "HELLO":
                stat["status"] = "caçando"
                self._emit("instance_update", {"client_id": client_id, "status": "caçando", "attempts": stat["attempts"]})

            elif cmd == "ATTEMPT":
                attempt_num = int(parts[1]) if len(parts) > 1 else stat["attempts"] + 1
                stat["attempts"] = attempt_num
                stat["status"] = "caçando"
                self.total_attempts = self.banked_attempts + sum(
                    s.get("attempts", 0) for s in self.instance_stats.values()
                )
                self._emit("attempt_update", {
                    "client_id": client_id,
                    "instance_attempts": attempt_num,
                    "total_attempts": self.total_attempts,
                })

            elif cmd == "RESET":
                stat["status"] = "resetando"
                self._emit("instance_update", {"client_id": client_id, "status": "resetando", "attempts": stat["attempts"]})

            elif cmd == "SHINY":
                self.shiny_found = True
                pv = parts[1] if len(parts) > 1 else "?"
                otid = parts[2] if len(parts) > 2 else "?"
                inst_attempts = parts[3] if len(parts) > 3 else str(stat["attempts"])

                self.total_attempts = self.banked_attempts + sum(
                    s.get("attempts", 0) for s in self.instance_stats.values()
                )

                stat["status"] = "★ SHINY!"
                self.shiny_info = {
                    "instance": client_id,
                    "pv": pv,
                    "otid": otid,
                    "attempts_this_instance": inst_attempts,
                    "total_attempts": self.total_attempts,
                }

                # Envia STOP para todas as outras instâncias
                for cid, cconn in list(self.clients.items()):
                    if cid != client_id:
                        try:
                            cconn.send(b"STOP\n")
                        except Exception:
                            pass

                self._emit("shiny_found", self.shiny_info)


class InstanceManager:
    """Gerencia a criação de arquivos de instâncias e os subprocessos do mGBA."""

    def __init__(self, config: HuntConfig):
        self.config = config
        self.processes: List[subprocess.Popen] = []
        self.instance_dirs: List[Path] = []

    def setup_instances(self) -> List[Path]:
        """Cria os diretórios e copia os arquivos ROM e SAV para cada instância."""
        rom_path = Path(self.config.rom_path)
        sav_path = Path(self.config.sav_path)

        if not rom_path.exists():
            raise FileNotFoundError(f"ROM não encontrada: {rom_path}")
        if not sav_path.exists():
            raise FileNotFoundError(f"SAV não encontrado: {sav_path}")

        instances_dir = self.config.instances_dir
        instances_dir.mkdir(parents=True, exist_ok=True)
        self.instance_dirs.clear()

        rom_name = rom_path.name
        sav_name = sav_path.name

        for i in range(1, self.config.num_instances + 1):
            inst_dir = instances_dir / f"instance_{i}"
            inst_dir.mkdir(parents=True, exist_ok=True)
            self.instance_dirs.append(inst_dir)

            inst_rom = inst_dir / rom_name
            inst_sav = inst_dir / sav_name

            shutil.copy2(rom_path, inst_rom)
            shutil.copy2(sav_path, inst_sav)

            # Validação rápida de integridade de tamanho
            if inst_rom.stat().st_size != rom_path.stat().st_size:
                raise IOError(f"Cópia da ROM corrompida na instância {i}")
            if inst_sav.stat().st_size != sav_path.stat().st_size:
                raise IOError(f"Cópia do SAV corrompida na instância {i}")

        return self.instance_dirs

    def launch_instances(self, on_launch: Optional[Callable[[int, int], None]] = None) -> int:
        """
        Lança as instâncias do mGBA.
        Retorna a quantidade de instâncias iniciadas com sucesso.
        """
        self.processes.clear()
        rom_path = Path(self.config.rom_path)
        rom_name = rom_path.name
        instances_dir = self.config.instances_dir

        for i in range(1, self.config.num_instances + 1):
            inst_rom = instances_dir / f"instance_{i}" / rom_name
            try:
                proc = subprocess.Popen(
                    [self.config.mgba_path, str(inst_rom)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.processes.append(proc)
                if on_launch:
                    on_launch(i, proc.pid)
                time.sleep(0.25)
            except Exception as e:
                raise RuntimeError(f"Falha ao iniciar instância #{i}: {e}")

        return self.alive_count()

    def kill_all(self, keep_instance: Optional[int] = None):
        """Fecha todos os processos do mGBA (exceto keep_instance se informado)."""
        for i, proc in enumerate(self.processes):
            if keep_instance is not None and (i + 1) == keep_instance:
                continue
            try:
                proc.terminate()
            except Exception:
                pass

        time.sleep(0.5)

        for i, proc in enumerate(self.processes):
            if keep_instance is not None and (i + 1) == keep_instance:
                continue
            try:
                proc.kill()
            except Exception:
                pass

    def alive_count(self) -> int:
        """Retorna quantos processos mGBA ainda estão vivos."""
        return sum(1 for p in self.processes if p.poll() is None)
