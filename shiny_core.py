#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shiny_core.py
Módulo central para o Hunter Shiny.
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
MAGIKARP_LUA_PATH = SCRIPT_DIR / "shiny_magi.lua"
EMERALD_LUA_PATH = SCRIPT_DIR / "iniciais_emerald.lua"

# Se algum dos scripts Lua não for encontrado na pasta do .exe, tenta extrair dos arquivos empacotados
for bundled_name, bundled_var in [
    ("shiny_hunt.lua", DEFAULT_LUA_PATH),
    ("shiny_magi.lua", MAGIKARP_LUA_PATH),
    ("iniciais_emerald.lua", EMERALD_LUA_PATH),
]:
    if not bundled_var.exists() and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / bundled_name
        if bundled.exists():
            try:
                shutil.copy2(bundled, bundled_var)
            except Exception:
                pass

CONFIG_FILE = SCRIPT_DIR / "config.json"


@dataclass
class HuntConfig:
    """Configurações da caçada."""
    mgba_path: str = r"C:\Program Files\mGBA\mGBA.exe"
    rom_path: str = r"C:\roms\FireRed.gba"
    sav_path: str = r"C:\roms\FireRed.sav"
    num_instances: int = 10
    server_port: int = 27015
    lua_script_path: str = str(MAGIKARP_LUA_PATH if MAGIKARP_LUA_PATH.exists() else DEFAULT_LUA_PATH)
    target_pokemon: str = "magikarp"  # "magikarp", "charmander", "starters", "treecko", "torchic", "mudkip"
    game: str = "firered"  # "firered" ou "emerald"
    emerald_starter: str = "treecko"  # "treecko", "torchic", "mudkip"

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
                    game = data.get("game", "firered")
                    emerald_starter = data.get("emerald_starter", "treecko")
                    default_lua = (
                        str(EMERALD_LUA_PATH if EMERALD_LUA_PATH.exists() else DEFAULT_LUA_PATH)
                        if game == "emerald"
                        else str(MAGIKARP_LUA_PATH if MAGIKARP_LUA_PATH.exists() else DEFAULT_LUA_PATH)
                    )
                    return cls(
                        mgba_path=data.get("mgba_path", r"C:\Program Files\mGBA\mGBA.exe"),
                        rom_path=data.get("rom_path", r"C:\roms\FireRed.gba"),
                        sav_path=data.get("sav_path", r"C:\roms\FireRed.sav"),
                        num_instances=int(data.get("num_instances", 10)),
                        server_port=int(data.get("server_port", 27015)),
                        lua_script_path=data.get("lua_script_path", default_lua),
                        target_pokemon=data.get("target_pokemon", "magikarp"),
                        game=game,
                        emerald_starter=emerald_starter,
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


def copy_to_clipboard(text: str) -> bool:
    """Copia uma string para a área de transferência do Windows."""
    if not text:
        return False
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["clip"],
            input=text.strip().encode("utf-16le"),
            check=True,
            creationflags=creationflags,
        )
        return True
    except Exception:
        pass
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text.strip())
        r.update()
        r.destroy()
        return True
    except Exception:
        pass
    return False


def register_mgba_recent_script(script_path: Path) -> bool:
    """
    Insere o script especificado no topo da lista [recentScripts] do mGBA (qt.ini).
    Assim, ao abrir o mGBA e ir em Tools > Scripting > File > Recent scripts,
    o script atual estará imediatamente disponível na 1ª posição (slot 0).
    """
    try:
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return False
        ini_path = Path(appdata) / "mGBA" / "qt.ini"
        if not ini_path.parent.exists():
            ini_path.parent.mkdir(parents=True, exist_ok=True)

        clean_path = str(Path(script_path).resolve()).replace("\\", "/")
        existing_scripts: List[str] = []

        content = ""
        if ini_path.exists():
            try:
                content = ini_path.read_text(encoding="utf-8")
            except Exception:
                content = ini_path.read_text(encoding="latin-1", errors="ignore")

        import re
        match = re.search(r"\[recentScripts\]\s*([\s\S]*?)(?=\n\[|\Z)", content)
        if match:
            for line in match.group(1).splitlines():
                line = line.strip()
                if "=" in line:
                    _, val = line.split("=", 1)
                    val = val.strip().strip('"').replace("\\", "/")
                    if val and val.lower() != clean_path.lower() and val not in existing_scripts:
                        existing_scripts.append(val)

        new_list = [clean_path] + existing_scripts[:9]
        lines = ["[recentScripts]"]
        for idx, s in enumerate(new_list):
            lines.append(f"{idx}={s}")
        new_section = "\n".join(lines)

        if match:
            new_content = content[:match.start()] + new_section + content[match.end():]
        else:
            new_content = content.rstrip() + ("\n\n" if content else "") + new_section + "\n"

        ini_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception:
        return False



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

    def _assign_free_id_locked(self) -> int:
        """Encontra o menor ID livre entre 1 e max_instances (deve ser chamado com self.lock)."""
        for i in range(1, self.max_instances + 1):
            if i not in self.clients:
                return i
        self._next_id += 1
        return self._next_id

    def _accept_loop(self):
        """Loop de aceitação de conexões."""
        while self._running and not self.shiny_found:
            try:
                if not self.server_socket:
                    break
                conn, _ = self.server_socket.accept()
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(conn,),
                    daemon=True,
                )
                thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket):
        """Processa mensagens recebidas de uma instância Lua."""
        client_id: Optional[int] = None
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
                    raw_msg = line.strip()
                    if raw_msg:
                        client_id = self._process_client_message(conn, client_id, raw_msg)
            except socket.timeout:
                continue
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                break

        # Cliente desconectou
        if client_id is not None:
            with self.lock:
                if self.clients.get(client_id) == conn:
                    self.clients.pop(client_id, None)
                    self.connected_count = len(self.clients)
                    stats = self.instance_stats.get(client_id)
                    if stats and stats["status"] != "★ SHINY!":
                        stats["status"] = "desconectado"
                        stats["last_update"] = datetime.now()
                    self.total_attempts = self.banked_attempts + sum(
                        s.get("attempts", 0) for s in self.instance_stats.values()
                    )

            self._emit("client_disconnected", {
                "client_id": client_id,
                "connected_count": self.connected_count,
                "total_attempts": self.total_attempts,
            })

    def _process_client_message(self, conn: socket.socket, current_id: Optional[int], msg: str) -> Optional[int]:
        """Trata mensagens de um cliente e retorna o ID associado (atual ou novo)."""
        parts = msg.split("|")
        cmd = parts[0]

        if cmd in ("HELLO", "IDENTIFY"):
            desired_id: Optional[int] = None
            if len(parts) > 1 and parts[1].strip().isdigit():
                val = int(parts[1].strip())
                if 1 <= val <= 30:
                    desired_id = val

            with self.lock:
                if desired_id is not None:
                    client_id = desired_id
                elif current_id is not None:
                    client_id = current_id
                else:
                    client_id = self._assign_free_id_locked()

                # Se o cliente mudou de ID ou havia outra conexão nesse ID
                if current_id is not None and current_id != client_id:
                    if self.clients.get(current_id) == conn:
                        self.clients.pop(current_id, None)

                old_conn = self.clients.get(client_id)
                if old_conn and old_conn != conn:
                    try:
                        old_conn.close()
                    except Exception:
                        pass

                self.clients[client_id] = conn
                self.connected_count = len(self.clients)

                if client_id not in self.instance_stats:
                    self.instance_stats[client_id] = {
                        "attempts": 0,
                        "status": "caçando",
                        "last_update": datetime.now(),
                    }
                else:
                    self.instance_stats[client_id]["status"] = "caçando"
                    self.instance_stats[client_id]["last_update"] = datetime.now()

            # Envia confirmação de ID para o Lua
            try:
                conn.send(f"ID|{client_id}\n".encode("utf-8"))
            except Exception:
                pass

            self._emit("client_connected", {
                "client_id": client_id,
                "connected_count": self.connected_count,
            })
            self._emit("instance_update", {
                "client_id": client_id,
                "status": "caçando",
                "attempts": self.instance_stats[client_id]["attempts"],
            })
            return client_id

        # Se não for HELLO/IDENTIFY e o cliente ainda não tiver ID, atribui um
        client_id = current_id
        if client_id is None:
            with self.lock:
                client_id = self._assign_free_id_locked()
                self.clients[client_id] = conn
                self.connected_count = len(self.clients)
                if client_id not in self.instance_stats:
                    self.instance_stats[client_id] = {
                        "attempts": 0,
                        "status": "caçando",
                        "last_update": datetime.now(),
                    }
            try:
                conn.send(f"ID|{client_id}\n".encode("utf-8"))
            except Exception:
                pass
            self._emit("client_connected", {
                "client_id": client_id,
                "connected_count": self.connected_count,
            })

        with self.lock:
            if client_id not in self.instance_stats:
                self.instance_stats[client_id] = {
                    "attempts": 0,
                    "status": "caçando",
                    "last_update": datetime.now(),
                }
            stat = self.instance_stats[client_id]
            stat["last_update"] = datetime.now()

            if cmd == "ATTEMPT":
                attempt_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else stat["attempts"] + 1
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
                self._emit("instance_update", {
                    "client_id": client_id,
                    "status": "resetando",
                    "attempts": stat["attempts"],
                })

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
                    if cid != client_id and cconn:
                        try:
                            cconn.send(b"STOP\n")
                        except Exception:
                            pass

                self._emit("shiny_found", self.shiny_info)

        return client_id


class InstanceManager:
    """Gerencia a criação de arquivos de instâncias e os subprocessos do mGBA."""

    def __init__(self, config: HuntConfig):
        self.config = config
        self.processes: List[subprocess.Popen] = []
        self.instance_dirs: List[Path] = []

    @staticmethod
    def _tag_rom_instance(rom_file: Path, instance_id: int):
        """Injeta o ID da instância no byte 0xB5 do header da ROM GBA e recalcula o checksum em 0xBD."""
        try:
            with open(rom_file, "r+b") as f:
                f.seek(0xA0)
                header_slice = bytearray(f.read(0xBD - 0xA0))  # 0xA0 até 0xBC (29 bytes)
                if len(header_slice) == (0xBD - 0xA0):
                    header_slice[0xB5 - 0xA0] = instance_id & 0xFF
                    calc = 0
                    for b in header_slice:
                        calc = (calc - b) & 0xFF
                    calc = (calc - 0x19) & 0xFF
                    f.seek(0xB5)
                    f.write(bytes([instance_id & 0xFF]))
                    f.seek(0xBD)
                    f.write(bytes([calc]))
        except Exception:
            pass

    def _create_instance_lua_script(self, inst_dir: Path, instance_id: int):
        """Copia os scripts Lua para a pasta da instância com o ID e alvo pré-definidos."""
        try:
            starter_val = self.config.emerald_starter if self.config.game == "emerald" else ""
            header = (
                f"-- [Configuracao de Instancia Automatica]\n"
                f"local SCRIPT_INSTANCE_ID = {instance_id}\n"
                f"local TARGET_STARTER = \"{starter_val}\"\n\n"
            )
            lua_src = Path(self.config.lua_script_path)
            if lua_src.exists():
                content = lua_src.read_text(encoding="utf-8")
                (inst_dir / lua_src.name).write_text(header + content, encoding="utf-8")
                # Se o script selecionado não for shiny_hunt.lua, mantém também como shiny_hunt.lua
                if lua_src.name != "shiny_hunt.lua":
                    (inst_dir / "shiny_hunt.lua").write_text(header + content, encoding="utf-8")

            # Garante que shiny_hunt.lua, shiny_magi.lua e iniciais_emerald.lua estejam disponíveis na instância
            for default_file in (DEFAULT_LUA_PATH, MAGIKARP_LUA_PATH, EMERALD_LUA_PATH):
                if default_file.exists():
                    dst = inst_dir / default_file.name
                    if not dst.exists() or default_file == lua_src:
                        text = default_file.read_text(encoding="utf-8")
                        dst.write_text(header + text, encoding="utf-8")
        except Exception:
            pass

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

            # Limpa save states antigos de caçadas anteriores
            for old_ss in inst_dir.glob("*.ss*"):
                try:
                    old_ss.unlink()
                except Exception:
                    pass

            inst_rom = inst_dir / rom_name
            inst_sav = inst_dir / sav_name

            shutil.copy2(rom_path, inst_rom)
            shutil.copy2(sav_path, inst_sav)

            # Marca a cópia da ROM com o ID da instância
            self._tag_rom_instance(inst_rom, i)

            # Cria arquivo instance_id.txt na pasta da instância
            try:
                (inst_dir / "instance_id.txt").write_text(f"{i}\n", encoding="utf-8")
            except Exception:
                pass

            # Se for Pokémon Emerald, cria arquivo emerald_starter.txt na pasta da instância
            if self.config.game == "emerald":
                try:
                    (inst_dir / "emerald_starter.txt").write_text(f"{self.config.emerald_starter}\n", encoding="utf-8")
                except Exception:
                    pass

            # Cria script shiny_hunt.lua com ID pré-configurado na pasta da instância
            self._create_instance_lua_script(inst_dir, i)

            # Validação rápida de integridade de tamanho
            if inst_rom.stat().st_size != rom_path.stat().st_size:
                raise IOError(f"Cópia da ROM corrompida na instância {i}")
            if inst_sav.stat().st_size != sav_path.stat().st_size:
                raise IOError(f"Cópia do SAV corrompida na instância {i}")

        # Para Emerald, sincroniza TARGET_STARTER no script raiz e grava emerald_starter.txt
        if self.config.game == "emerald":
            try:
                starter_chosen = self.config.emerald_starter.strip().lower()
                (SCRIPT_DIR / "emerald_starter.txt").write_text(f"{starter_chosen}\n", encoding="utf-8")
                try:
                    (Path(self.config.rom_path).parent / "emerald_starter.txt").write_text(f"{starter_chosen}\n", encoding="utf-8")
                except Exception:
                    pass

                # Atualiza diretamente o script raiz iniciais_emerald.lua
                if EMERALD_LUA_PATH.exists():
                    import re
                    lua_text = EMERALD_LUA_PATH.read_text(encoding="utf-8")
                    lua_text = re.sub(
                        r'local TARGET_STARTER\s*=\s*.*',
                        f'local TARGET_STARTER = "{starter_chosen}"',
                        lua_text
                    )
                    EMERALD_LUA_PATH.write_text(lua_text, encoding="utf-8")
                    dist_lua = SCRIPT_DIR / "dist" / "iniciais_emerald.lua"
                    if dist_lua.exists():
                        dist_lua.write_text(lua_text, encoding="utf-8")
            except Exception:
                pass

        # Pré-configura o script atual no histórico [recentScripts] do mGBA (qt.ini)
        # e copia automaticamente o caminho completo para a Área de Transferência
        try:
            target_lua = Path(self.config.lua_script_path).resolve()
            register_mgba_recent_script(target_lua)
            copy_to_clipboard(str(target_lua))
        except Exception:
            pass

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
            inst_dir = instances_dir / f"instance_{i}"
            inst_rom = inst_dir / rom_name
            env = os.environ.copy()
            env["SHINY_INSTANCE_ID"] = str(i)
            if self.config.game == "emerald":
                env["SHINY_EMERALD_STARTER"] = self.config.emerald_starter
            try:
                proc = subprocess.Popen(
                    [self.config.mgba_path, str(inst_rom)],
                    cwd=str(inst_dir),
                    env=env,
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

    def find_shiny_instance(self, since: datetime) -> Optional[int]:
        """Retorna o número da instância cujo save state foi gravado após `since`."""
        threshold = since.timestamp() - 5.0  # Margem de tolerância para sincronização de relógio
        best_idx: Optional[int] = None
        best_mtime = 0.0
        for i in range(1, self.config.num_instances + 1):
            inst_dir = self.config.instances_dir / f"instance_{i}"
            for f in inst_dir.glob("*.ss*"):
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if m >= threshold and m > best_mtime:
                    best_idx, best_mtime = i, m
        return best_idx

    def alive_count(self) -> int:
        """Retorna quantos processos mGBA ainda estão vivos."""
        return sum(1 for p in self.processes if p.poll() is None)

