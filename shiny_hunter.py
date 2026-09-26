#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hunter Shiny v1.0
Gerenciador de instâncias mGBA para shiny hunting automatizado
Pokemon Fire Red (US) v1.0

Uso: python shiny_hunter.py
"""

import errno
import os
import sys
import time
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from datetime import datetime

# ======================== CONFIGURAÇÃO ========================

MGBA_PATH = r"C:\Program Files\mGBA\mGBA.exe"
ROM_DIR = r"C:\roms"
ROM_NAME = "FireRed.gba"
SAV_NAME = "FireRed.sav"
NUM_INSTANCES = 15
SERVER_PORT = 27015

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_LUA_SCRIPT = SCRIPT_DIR / "shiny_hunt.lua"
MAGIKARP_LUA_SCRIPT = SCRIPT_DIR / "shiny_magi.lua"
EMERALD_LUA_SCRIPT = SCRIPT_DIR / "iniciais_emerald.lua"
LUA_SCRIPT = MAGIKARP_LUA_SCRIPT if MAGIKARP_LUA_SCRIPT.exists() else DEFAULT_LUA_SCRIPT
TARGET_STARTER = "treecko"
SELECTED_GAME = "firered"
INSTANCES_DIR = Path(ROM_DIR) / "instances"


# ======================== CORES ANSI ========================

class C:
    """Cores ANSI para saída colorida no terminal."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    BG_GREEN  = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_RED    = "\033[41m"

    @staticmethod
    def star():
        return f"{C.YELLOW}★{C.RESET}"

    @staticmethod
    def check():
        return f"{C.GREEN}✓{C.RESET}"

    @staticmethod
    def cross():
        return f"{C.RED}✗{C.RESET}"

    @staticmethod
    def warn():
        return f"{C.YELLOW}⚠{C.RESET}"


# ======================== SERVIDOR TCP ========================

class ShinyServer:
    """
    Servidor TCP que coordena as instâncias Lua do mGBA.
    Cada instância Lua se conecta e envia mensagens de status.
    Quando uma encontra um shiny, notifica todas as outras para parar.
    """

    def __init__(self, port=SERVER_PORT):
        self.port = port
        self.server_socket = None
        self.clients = {}           # {client_id: socket}
        self.shiny_found = False
        self.shiny_info = None
        self.lock = threading.Lock()
        self.instance_stats = {}    # {client_id: {"attempts": N, "status": str}}
        self.total_attempts = 0
        self.banked_attempts = 0    # Tentativas acumuladas de instâncias desconectadas
        self._next_id = 0
        self.connected_count = 0
        self.start_time = None
        self._running = True

    def start(self):
        """Inicia o servidor TCP em uma thread separada."""
        self.start_time = datetime.now()
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)
        self.server_socket.bind(("127.0.0.1", self.port))
        self.server_socket.listen(NUM_INSTANCES + 5)

        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

    def stop(self):
        """Para o servidor e fecha todas as conexões."""
        self._running = False
        for conn in list(self.clients.values()):
            try:
                conn.close()
            except Exception:
                pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

    def _assign_free_id_locked(self):
        """Encontra o menor ID livre entre 1 e NUM_INSTANCES (deve ser chamado com self.lock)."""
        for i in range(1, NUM_INSTANCES + 1):
            if i not in self.clients:
                return i
        self._next_id += 1
        return self._next_id

    def _accept_loop(self):
        """Loop que aceita novas conexões de instâncias Lua."""
        while self._running and not self.shiny_found:
            try:
                conn, addr = self.server_socket.accept()
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

    def _handle_client(self, conn):
        """Lida com mensagens de uma instância Lua."""
        client_id = None
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
                    self.total_attempts = self.banked_attempts + sum(
                        s.get("attempts", 0) for s in self.instance_stats.values()
                    )

    def _process_client_message(self, conn, current_id, msg):
        """Processa mensagens de um cliente e retorna o ID associado (atual ou novo)."""
        parts = msg.split("|")
        cmd = parts[0]

        if cmd in ("HELLO", "IDENTIFY"):
            desired_id = None
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
                    }
                else:
                    self.instance_stats[client_id]["status"] = "caçando"

            try:
                conn.send(f"ID|{client_id}\n".encode("utf-8"))
            except Exception:
                pass

            return client_id

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
                    }
            try:
                conn.send(f"ID|{client_id}\n".encode("utf-8"))
            except Exception:
                pass

        with self.lock:
            if client_id not in self.instance_stats:
                self.instance_stats[client_id] = {
                    "attempts": 0,
                    "status": "caçando",
                }
            stat = self.instance_stats[client_id]

            if cmd == "ATTEMPT":
                attempt_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else stat["attempts"] + 1
                stat["attempts"] = attempt_num
                stat["status"] = "caçando"
                self.total_attempts = self.banked_attempts + sum(
                    s.get("attempts", 0) for s in self.instance_stats.values()
                )

            elif cmd == "RESET":
                stat["status"] = "resetando"

            elif cmd == "SHINY":
                self.shiny_found = True
                pv = parts[1] if len(parts) > 1 else "?"
                otid = parts[2] if len(parts) > 2 else "?"
                inst_attempts = parts[3] if len(parts) > 3 else str(stat["attempts"])

                self.total_attempts = self.banked_attempts + sum(
                    s.get("attempts", 0) for s in self.instance_stats.values()
                )

                self.shiny_info = {
                    "instance": client_id,
                    "pv": pv,
                    "otid": otid,
                    "attempts_this_instance": inst_attempts,
                    "total_attempts": self.total_attempts,
                }
                stat["status"] = "★ SHINY!"

                # Envia STOP para todas as outras instâncias
                for cid, cconn in self.clients.items():
                    if cid != client_id and cconn:
                        try:
                            cconn.send(b"STOP\n")
                        except Exception:
                            pass

        return client_id


# ======================== GERENCIADOR DE INSTÂNCIAS ========================

class InstanceManager:
    """Gerencia a criação de diretórios e processos mGBA."""

    def __init__(self):
        self.processes = []

    @staticmethod
    def _tag_rom_instance(rom_file, instance_id):
        """Injeta o ID da instância no byte 0xB5 do header da ROM GBA e recalcula o checksum em 0xBD."""
        try:
            with open(rom_file, "r+b") as f:
                f.seek(0xA0)
                header_slice = bytearray(f.read(0xBD - 0xA0))
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

    def _create_instance_lua_script(self, inst_dir, instance_id):
        """Copia os scripts Lua para a pasta da instância com o ID e alvo pré-definidos."""
        try:
            starter_val = TARGET_STARTER if SELECTED_GAME == "emerald" else ""
            header = (
                f"-- [Configuracao de Instancia Automatica]\n"
                f"local SCRIPT_INSTANCE_ID = {instance_id}\n"
                f"local TARGET_STARTER = \"{starter_val}\"\n\n"
            )
            if LUA_SCRIPT.exists():
                content = LUA_SCRIPT.read_text(encoding="utf-8")
                (inst_dir / LUA_SCRIPT.name).write_text(header + content, encoding="utf-8")
                if LUA_SCRIPT.name != "shiny_hunt.lua":
                    (inst_dir / "shiny_hunt.lua").write_text(header + content, encoding="utf-8")

            for default_file in (DEFAULT_LUA_SCRIPT, MAGIKARP_LUA_SCRIPT, EMERALD_LUA_SCRIPT):
                if default_file.exists():
                    dst = inst_dir / default_file.name
                    text = default_file.read_text(encoding="utf-8")
                    dst.write_text(header + text, encoding="utf-8")
        except Exception:
            pass

    def setup_instances(self):
        """Cria diretórios de instância com cópias da ROM e SAV."""
        rom_path = Path(ROM_DIR) / ROM_NAME
        sav_path = Path(ROM_DIR) / SAV_NAME

        if not rom_path.exists():
            print(f"  {C.cross()} ROM não encontrada: {rom_path}")
            sys.exit(1)
        if not sav_path.exists():
            print(f"  {C.cross()} SAV não encontrado: {sav_path}")
            sys.exit(1)

        INSTANCES_DIR.mkdir(parents=True, exist_ok=True)

        for i in range(1, NUM_INSTANCES + 1):
            inst_dir = INSTANCES_DIR / f"instance_{i}"
            inst_dir.mkdir(parents=True, exist_ok=True)

            # Limpa save states antigos de caçadas anteriores
            for old_ss in inst_dir.glob("*.ss*"):
                try:
                    old_ss.unlink()
                except Exception:
                    pass

            inst_rom = inst_dir / ROM_NAME
            inst_sav = inst_dir / SAV_NAME

            shutil.copy2(rom_path, inst_rom)
            shutil.copy2(sav_path, inst_sav)

            # Marca a cópia da ROM com o ID da instância
            self._tag_rom_instance(inst_rom, i)

            # Cria arquivo instance_id.txt na pasta da instância
            try:
                (inst_dir / "instance_id.txt").write_text(f"{i}\n", encoding="utf-8")
            except Exception:
                pass

            # Para Pokémon Emerald, cria arquivo emerald_starter.txt na pasta da instância
            if SELECTED_GAME == "emerald":
                try:
                    (inst_dir / "emerald_starter.txt").write_text(f"{TARGET_STARTER}\n", encoding="utf-8")
                except Exception:
                    pass

            # Cria script shiny_hunt.lua na pasta da instância
            self._create_instance_lua_script(inst_dir, i)

            # Validação: verifica se as cópias têm o tamanho correto
            if inst_rom.stat().st_size != rom_path.stat().st_size:
                print(f"  {C.cross()} Cópia da ROM corrompida na instância {i}")
                sys.exit(1)
            if inst_sav.stat().st_size != sav_path.stat().st_size:
                print(f"  {C.cross()} Cópia do SAV corrompida na instância {i}")
                sys.exit(1)

        # Pré-configura no histórico [recentScripts] do mGBA (qt.ini) e copia para o Clipboard
        try:
            from shiny_core import register_mgba_recent_script, copy_to_clipboard
            target_lua = Path(LUA_SCRIPT).resolve()
            register_mgba_recent_script(target_lua)
            copy_to_clipboard(str(target_lua))
        except Exception:
            pass

        print(f"  {C.check()} {NUM_INSTANCES} diretórios de instância criados em:")
        print(f"      {C.DIM}{INSTANCES_DIR}{C.RESET}")

    def launch_instances(self):
        """Lança os processos mGBA."""
        for i in range(1, NUM_INSTANCES + 1):
            inst_dir = INSTANCES_DIR / f"instance_{i}"
            inst_rom = inst_dir / ROM_NAME
            env = os.environ.copy()
            env["SHINY_INSTANCE_ID"] = str(i)
            if SELECTED_GAME == "emerald":
                env["SHINY_EMERALD_STARTER"] = TARGET_STARTER
            try:
                proc = subprocess.Popen(
                    [MGBA_PATH, str(inst_rom)],
                    cwd=str(inst_dir),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.processes.append(proc)
                print(f"      {C.DIM}Instância {i:2d} → PID {proc.pid}{C.RESET}")
                time.sleep(0.3)  # Espaçar lançamentos para não sobrecarregar
            except Exception as e:
                print(f"  {C.cross()} Falha ao lançar instância {i}: {e}")

        alive = sum(1 for p in self.processes if p.poll() is None)
        print(f"  {C.check()} {alive} instâncias do mGBA abertas")

    def kill_all(self, keep_instance=None):
        """Fecha todos os processos mGBA (exceto keep_instance, se definido)."""
        for i, proc in enumerate(self.processes):
            if keep_instance is not None and (i + 1) == keep_instance:
                continue
            try:
                proc.terminate()
            except Exception:
                pass

        time.sleep(1.5)

        for i, proc in enumerate(self.processes):
            if keep_instance is not None and (i + 1) == keep_instance:
                continue
            try:
                proc.kill()
            except Exception:
                pass

    def alive_count(self):
        """Retorna quantos processos mGBA ainda estão rodando."""
        return sum(1 for p in self.processes if p.poll() is None)

    def find_shiny_instance(self, since):
        """Retorna o número da instância cujo save state foi gravado após `since`."""
        threshold = since.timestamp() - 5.0
        best_idx = None
        best_mtime = 0.0
        for i in range(1, NUM_INSTANCES + 1):
            inst_dir = INSTANCES_DIR / f"instance_{i}"
            for f in inst_dir.glob("*.ss*"):
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if m >= threshold and m > best_mtime:
                    best_idx, best_mtime = i, m
        return best_idx


# ======================== DISPLAY ========================

def print_banner():
    """Exibe o banner do programa."""
    game_title = "Pokemon Emerald (US)" if SELECTED_GAME == "emerald" else "Pokemon Fire Red (US)"
    target_info = f"Inicial: {TARGET_STARTER.capitalize()}" if SELECTED_GAME == "emerald" else "Kanto / Rota 4"
    print()
    print(f"  {C.YELLOW}{C.BOLD}╔══════════════════════════════════════════════════════╗{C.RESET}")
    print(f"  {C.YELLOW}{C.BOLD}║  {C.star()}  Hunter Shiny v1.0  {C.star()}                           ║{C.RESET}")
    print(f"  {C.YELLOW}{C.BOLD}║  {game_title:<25} — {NUM_INSTANCES} Instâncias       ║{C.RESET}")
    print(f"  {C.YELLOW}{C.BOLD}║  {target_info:<50}║{C.RESET}")
    print(f"  {C.YELLOW}{C.BOLD}╚══════════════════════════════════════════════════════╝{C.RESET}")
    print()


def print_prerequisites():
    """Verifica e exibe os pré-requisitos."""
    print(f"  {C.CYAN}{C.BOLD}══ Verificando pré-requisitos ══{C.RESET}")
    print()

    ok = True

    if Path(MGBA_PATH).exists():
        print(f"  {C.check()} mGBA:       {C.DIM}{MGBA_PATH}{C.RESET}")
    else:
        print(f"  {C.cross()} mGBA não encontrado: {MGBA_PATH}")
        ok = False

    rom_path = Path(ROM_DIR) / ROM_NAME
    if rom_path.exists():
        size_mb = rom_path.stat().st_size / (1024 * 1024)
        print(f"  {C.check()} ROM:        {C.DIM}{rom_path} ({size_mb:.1f} MB){C.RESET}")
    else:
        print(f"  {C.cross()} ROM não encontrada: {rom_path}")
        ok = False

    sav_path = Path(ROM_DIR) / SAV_NAME
    if sav_path.exists():
        size_kb = sav_path.stat().st_size / 1024
        print(f"  {C.check()} Save:       {C.DIM}{sav_path} ({size_kb:.1f} KB){C.RESET}")
    else:
        print(f"  {C.cross()} Save não encontrado: {sav_path}")
        ok = False

    if LUA_SCRIPT.exists():
        print(f"  {C.check()} Lua Script: {C.DIM}{LUA_SCRIPT}{C.RESET}")
    else:
        print(f"  {C.cross()} Script Lua não encontrado: {LUA_SCRIPT}")
        ok = False

    print()

    if not ok:
        print(f"  {C.RED}{C.BOLD}Pré-requisitos não atendidos. Corrija os erros acima.{C.RESET}")
        sys.exit(1)

    return True


def print_instructions():
    """Exibe instruções para o usuário carregar o script Lua."""
    print()
    print(f"  {C.CYAN}{C.BOLD}══ INSTRUÇÕES ══{C.RESET}")
    print()
    if SELECTED_GAME == "emerald":
        starter_names = {
            "treecko": "Treecko (Planta - Seta Esquerda ◀)",
            "torchic": "Torchic (Fogo - Centro ●)",
            "mudkip": "Mudkip (Água - Seta Direita ▶)",
        }
        st_name = starter_names.get(TARGET_STARTER, TARGET_STARTER.capitalize())
        print(f"  {C.YELLOW}Jogo:{C.RESET}  {C.BOLD}Pokémon Emerald (US){C.RESET}")
        print(f"  {C.YELLOW}Alvo:{C.RESET}  {C.BOLD}Inicial de Hoenn: {st_name}{C.RESET}")
        print(f"  {C.YELLOW}Setup no jogo:{C.RESET} Salve em frente à bolsa do Prof. Birch na Rota 101 com 0 Pokémon na party.")
    elif "magi" in LUA_SCRIPT.name.lower():
        print(f"  {C.YELLOW}Alvo:{C.RESET} {C.BOLD}Magikarp (Vendedor Rota 4 - Slot Livre){C.RESET}")
        print(f"  {C.YELLOW}Setup no jogo:{C.RESET} Salve em frente ao vendedor com pelo menos 1 slot livre na party.")
    else:
        print(f"  {C.YELLOW}Alvo:{C.RESET} {C.BOLD}Iniciais de Kanto (Bulbasaur / Charmander / Squirtle - Slot 1){C.RESET}")
        print(f"  {C.YELLOW}Setup no jogo:{C.RESET} Salve em frente à Pokébola do inicial desejado com 0 Pokémon na party.")
    print()
    print(f"  {C.GREEN}{C.BOLD}★ ATALHO RÁPIDO (O script já foi pré-configurado no seu mGBA e copiado pro Clipboard!){C.RESET}")
    print(f"  Para {C.BOLD}CADA{C.RESET} janela do mGBA (todas as {NUM_INSTANCES}):")
    print()
    print(f"    {C.CYAN}Opção 1 (1 Clique):{C.RESET} Menu {C.BOLD}Tools{C.RESET} → {C.BOLD}Scripting...{C.RESET} → {C.BOLD}File{C.RESET} → {C.BOLD}Recent scripts{C.RESET} → {C.BOLD}[0] {LUA_SCRIPT.name}{C.RESET}")
    print(f"    {C.CYAN}Opção 2 (Teclado):{C.RESET}  Menu {C.BOLD}Tools{C.RESET} → {C.BOLD}Scripting...{C.RESET} → {C.BOLD}Ctrl+O{C.RESET} → {C.BOLD}Ctrl+V{C.RESET} → {C.BOLD}Enter{C.RESET}")
    print()
    print(f"  {C.warn()} O script conecta automaticamente ao servidor!")
    print()


def format_elapsed(start_time):
    """Formata o tempo decorrido."""
    elapsed = (datetime.now() - start_time).total_seconds()
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def print_status_line(server):
    """Imprime a linha de status atualizada."""
    elapsed = format_elapsed(server.start_time)

    # Monta barra de instâncias
    inst_bar = ""
    for cid in sorted(server.instance_stats.keys()):
        stats = server.instance_stats[cid]
        att = stats.get("attempts", 0)
        status = stats.get("status", "?")

        if status == "★ SHINY!":
            inst_bar += f"{C.GREEN}{C.BOLD}★{att}{C.RESET} "
        elif status == "caçando":
            inst_bar += f"{C.WHITE}{att}{C.RESET} "
        elif status == "resetando":
            inst_bar += f"{C.YELLOW}{att}{C.RESET} "
        elif status == "desconectado":
            inst_bar += f"{C.RED}{att}{C.RESET} "
        else:
            inst_bar += f"{C.DIM}{att}{C.RESET} "

    status_str = (
        f"\r  {C.BLUE}[{elapsed}]{C.RESET} "
        f"Inst: {C.GREEN}{server.connected_count}/{NUM_INSTANCES}{C.RESET} | "
        f"Total: {C.YELLOW}{C.BOLD}{server.total_attempts}{C.RESET}"
    )

    if inst_bar:
        status_str += f" | [{inst_bar.strip()}]"

    # Limpa a linha e imprime
    print(f"\033[2K{status_str}", end="", flush=True)


def print_shiny_celebration(info, start_time):
    """Exibe a celebração quando um shiny é encontrado!"""
    elapsed = (datetime.now() - start_time).total_seconds()
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)

    print()
    print()
    print(f"  {C.YELLOW}{C.BOLD}")
    print(f"  ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★")
    print(f"  ★                                                    ★")
    print(f"  ★               SHINY ENCONTRADO!!!                  ★")
    print(f"  ★                                                    ★")
    print(f"  ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★")
    print(f"  {C.RESET}")

    inst_num = info.get("instance", "?")
    dir_inst = info.get("dir_instance", inst_num)
    print(f"  {C.GREEN}Instância:          {C.WHITE}{C.BOLD}#{inst_num}{C.RESET}")
    print(f"  {C.GREEN}Personality Value:  {C.WHITE}{info.get('pv', '?')}{C.RESET}")
    print(f"  {C.GREEN}OT ID:             {C.WHITE}{info.get('otid', '?')}{C.RESET}")
    print(f"  {C.GREEN}Tentativas (inst):  {C.WHITE}{info.get('attempts_this_instance', '?')}{C.RESET}")
    print(f"  {C.GREEN}Tentativas (total): {C.WHITE}{C.BOLD}{info.get('total_attempts', '?')}{C.RESET}")
    print(f"  {C.GREEN}Tempo total:        {C.WHITE}{hours:02d}h {minutes:02d}m {seconds:02d}s{C.RESET}")
    print()

    inst_dir = INSTANCES_DIR / f"instance_{dir_inst}"
    print(f"  {C.CYAN}O save state foi salvo no {C.BOLD}Slot 1{C.RESET}{C.CYAN} da instância #{dir_inst}.{C.RESET}")
    print(f"  {C.CYAN}Para continuar jogando:{C.RESET}")
    print(f"    1. Abra o mGBA com a ROM: {C.WHITE}{inst_dir / ROM_NAME}{C.RESET}")
    print(f"    2. Carregue o save state: {C.WHITE}File > Load State > Slot 1{C.RESET}")
    print()


# ======================== MAIN ========================

def run_cli():
    """Função principal do programa em modo terminal/CLI."""
    global LUA_SCRIPT, SELECTED_GAME, TARGET_STARTER

    # Habilita cores ANSI no terminal do Windows
    os.system("")

    # Opções de linha de comando para jogo e alvo
    if "--emerald" in sys.argv or "--esmeralda" in sys.argv:
        SELECTED_GAME = "emerald"
        LUA_SCRIPT = EMERALD_LUA_SCRIPT
    elif "--firered" in sys.argv or "--fire-red" in sys.argv:
        SELECTED_GAME = "firered"

    if "--treecko" in sys.argv:
        SELECTED_GAME = "emerald"
        TARGET_STARTER = "treecko"
        LUA_SCRIPT = EMERALD_LUA_SCRIPT
    elif "--torchic" in sys.argv:
        SELECTED_GAME = "emerald"
        TARGET_STARTER = "torchic"
        LUA_SCRIPT = EMERALD_LUA_SCRIPT
    elif "--mudkip" in sys.argv:
        SELECTED_GAME = "emerald"
        TARGET_STARTER = "mudkip"
        LUA_SCRIPT = EMERALD_LUA_SCRIPT
    elif "--iniciais" in sys.argv or "--starters" in sys.argv or "--charmander" in sys.argv:
        if SELECTED_GAME != "emerald":
            LUA_SCRIPT = DEFAULT_LUA_SCRIPT
    elif "--magikarp" in sys.argv:
        SELECTED_GAME = "firered"
        LUA_SCRIPT = MAGIKARP_LUA_SCRIPT

    for i, arg in enumerate(sys.argv):
        if arg in ("--game", "-g") and i + 1 < len(sys.argv):
            g = sys.argv[i + 1].lower()
            if "eme" in g:
                SELECTED_GAME = "emerald"
                LUA_SCRIPT = EMERALD_LUA_SCRIPT
            else:
                SELECTED_GAME = "firered"
        elif arg in ("--starter", "-s") and i + 1 < len(sys.argv):
            s = sys.argv[i + 1].lower()
            SELECTED_GAME = "emerald"
            LUA_SCRIPT = EMERALD_LUA_SCRIPT
            if "mud" in s or "agua" in s:
                TARGET_STARTER = "mudkip"
            elif "tor" in s or "fogo" in s:
                TARGET_STARTER = "torchic"
            else:
                TARGET_STARTER = "treecko"
        elif arg == "--target" and i + 1 < len(sys.argv):
            target = sys.argv[i + 1].lower()
            if "tree" in target:
                SELECTED_GAME = "emerald"
                TARGET_STARTER = "treecko"
                LUA_SCRIPT = EMERALD_LUA_SCRIPT
            elif "tor" in target:
                SELECTED_GAME = "emerald"
                TARGET_STARTER = "torchic"
                LUA_SCRIPT = EMERALD_LUA_SCRIPT
            elif "mud" in target:
                SELECTED_GAME = "emerald"
                TARGET_STARTER = "mudkip"
                LUA_SCRIPT = EMERALD_LUA_SCRIPT
            elif "magi" in target:
                SELECTED_GAME = "firered"
                LUA_SCRIPT = MAGIKARP_LUA_SCRIPT
            else:
                LUA_SCRIPT = DEFAULT_LUA_SCRIPT
        elif arg == "--lua" and i + 1 < len(sys.argv):
            LUA_SCRIPT = Path(sys.argv[i + 1]).resolve()

    if SELECTED_GAME == "emerald":
        try:
            (SCRIPT_DIR / "emerald_starter.txt").write_text(f"{TARGET_STARTER}\n", encoding="utf-8")
            if EMERALD_LUA_SCRIPT.exists():
                import re
                txt = EMERALD_LUA_SCRIPT.read_text(encoding="utf-8")
                txt = re.sub(
                    r'local TARGET_STARTER\s*=\s*.*',
                    f'local TARGET_STARTER = "{TARGET_STARTER}"',
                    txt
                )
                EMERALD_LUA_SCRIPT.write_text(txt, encoding="utf-8")
                dist_lua = SCRIPT_DIR / "dist" / "iniciais_emerald.lua"
                if dist_lua.exists():
                    dist_lua.write_text(txt, encoding="utf-8")
        except Exception:
            pass

    print_banner()
    print_prerequisites()

    # ── Preparar instâncias ──
    print(f"  {C.CYAN}{C.BOLD}══ Preparando instâncias ══{C.RESET}")
    print()

    manager = InstanceManager()
    manager.setup_instances()
    print()

    # ── Iniciar servidor TCP ──
    print(f"  {C.CYAN}{C.BOLD}══ Iniciando servidor ══{C.RESET}")
    print()

    server = ShinyServer(SERVER_PORT)
    try:
        server.start()
    except OSError as e:
        is_addr_in_use = (
            getattr(e, "winerror", None) == 10048
            or e.errno == errno.EADDRINUSE
        )
        if is_addr_in_use:
            print(f"  {C.cross()} Porta {SERVER_PORT} já em uso!")
            print(f"      Feche outras instâncias do programa e tente novamente.")
            sys.exit(1)
        raise

    print(f"  {C.check()} Servidor TCP rodando em {C.WHITE}127.0.0.1:{SERVER_PORT}{C.RESET}")
    print()

    # ── Abrir mGBA ──
    print(f"  {C.CYAN}{C.BOLD}══ Abrindo mGBA ══{C.RESET}")
    print()

    manager.launch_instances()
    print()

    # ── Instruções ──
    print_instructions()

    # ── Monitoramento ──
    print(f"  {C.CYAN}{C.BOLD}══ Monitoramento ativo ══{C.RESET}")
    print()
    print(f"  Aguardando instâncias carregarem o script Lua...")
    print(f"  Pressione {C.RED}{C.BOLD}Ctrl+C{C.RESET} para encerrar tudo")
    print()

    try:
        while not server.shiny_found:
            print_status_line(server)
            time.sleep(1)

            # Verifica se todos os processos mGBA morreram
            alive = manager.alive_count()
            if alive == 0 and len(manager.processes) > 0:
                print()
                print()
                print(f"  {C.warn()} Todos os processos mGBA foram fechados.")
                print(f"  {C.DIM}Encerrando o programa...{C.RESET}")
                server.stop()
                break

    except KeyboardInterrupt:
        print()
        print()
        print(f"  {C.YELLOW}{C.BOLD}Encerrando...{C.RESET}")
        manager.kill_all()
        server.stop()
        print(f"  {C.check()} Todos os processos encerrados.")
        print()
        sys.exit(0)

    # ── Shiny encontrado! ──
    if server.shiny_found:
        shiny_instance = server.shiny_info.get("instance")

        # Identifica a instância correta pelo save state
        keep = manager.find_shiny_instance(server.start_time)
        if keep is None:
            print(f"  {C.warn()} Não foi possível identificar o save state recente; mantendo janela #{shiny_instance}.")
            keep = shiny_instance

        if keep is not None:
            if str(shiny_instance) != str(keep):
                print(f"  {C.warn()} Sincronizando: script reportou #{shiny_instance}, mas save state foi na #{keep}.")
                server.shiny_info["instance"] = keep
            server.shiny_info["dir_instance"] = keep
            manager.kill_all(keep_instance=keep)
        else:
            manager.kill_all()

        # Celebração!
        print_shiny_celebration(server.shiny_info, server.start_time)

        try:
            input(f"  Pressione {C.GREEN}{C.BOLD}Enter{C.RESET} para fechar a última instância...")
        except (KeyboardInterrupt, EOFError):
            pass

        # Fecha a instância restante
        manager.kill_all()

    server.stop()

    # ── Limpeza ──
    print()
    print(f"  {C.check()} Programa encerrado.")
    print(f"  {C.DIM}Os diretórios de instância foram mantidos em:{C.RESET}")
    print(f"  {C.DIM}{INSTANCES_DIR}{C.RESET}")
    print()


def main():
    """Ponto de entrada: abre o GUI por padrão ou o CLI se --cli for especificado."""
    if "--cli" in sys.argv:
        run_cli()
    else:
        try:
            from shiny_hunter_gui import main as gui_main
            gui_main()
        except Exception as e:
            print(f"Não foi possível abrir o GUI ({e}). Iniciando em modo CLI...")
            run_cli()


if __name__ == "__main__":
    main()

