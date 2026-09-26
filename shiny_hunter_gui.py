#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hunter Shiny — Interface Gráfica (GUI)
Pokemon Fire Red (US) v1.0
Gerenciador automatizado com mGBA e scripts Lua.
"""

import ctypes
import os
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Importa o módulo central com regras de negócio
from shiny_core import (
    CONFIG_FILE,
    DEFAULT_LUA_PATH,
    MAGIKARP_LUA_PATH,
    EMERALD_LUA_PATH,
    HuntConfig,
    InstanceManager,
    ShinyServer,
    calculate_shiny_chance,
    copy_to_clipboard,
    format_elapsed,
    register_mgba_recent_script,
)

# Habilita suporte a High-DPI no Windows para fontes nítidas
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class DarkTheme:
    """Paleta de cores e estilos para tema escuro moderno."""
    BG_DARK       = "#11111b"  # Fundo geral profundo
    SURFACE_0     = "#181825"  # Superfície de cards
    SURFACE_1     = "#1e1e2e"  # Superfície secundária / inputs
    SURFACE_2     = "#313244"  # Bordas e divisores
    SURFACE_HOVER = "#45475a"  # Elementos em hover

    TEXT_MAIN     = "#cdd6f4"  # Texto principal claro
    TEXT_MUTED    = "#a6adc8"  # Texto secundário
    TEXT_DIM      = "#6c7086"  # Detalhes discretos

    ACCENT_GREEN  = "#a6e3a1"  # Sucesso / Iniciar / Conectado
    ACCENT_GREEN_HOVER = "#94e2d5"
    ACCENT_RED    = "#f38ba8"  # Perigo / Parar / Desconectado
    ACCENT_RED_HOVER = "#eba0ac"
    ACCENT_YELLOW = "#f9e2af"  # Alerta / Reset / Shiny
    ACCENT_BLUE   = "#89b4fa"  # Info / Primário
    ACCENT_PURPLE = "#cba6f7"  # Destaque / Shiny
    ACCENT_ORANGE = "#fab387"  # Fogo / Pokémon


class ShinyHuntGUI:
    """Interface Gráfica principal do ShinyHunt."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Hunter Shiny — Pokémon Fire Red")
        self.root.geometry("1020x760")
        self.root.minsize(860, 640)
        self.root.configure(bg=DarkTheme.BG_DARK)

        # Estado da aplicação
        self.config = HuntConfig.load()
        self.server: Optional[ShinyServer] = None
        self.manager: Optional[InstanceManager] = None
        self.is_hunting = False
        self.shiny_celebrated = False
        self.start_time: Optional[datetime] = None
        self.event_queue = queue.Queue()
        self.pid_map = {}  # {instance_id: pid}

        # Configura estilos ttk
        self._setup_styles()

        # Constrói a interface
        self._create_widgets()

        # Preenche os campos com a configuração salva
        self._populate_config_fields()

        # Inicia loop de verificação de eventos e atualização periódica
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_window)
        self.root.after(100, self._process_event_queue)
        self.root.after(1000, self._tick_timer)

    def _setup_styles(self):
        """Define o estilo customizado para os componentes ttk."""
        style = ttk.Style()
        style.theme_use("clam")

        # Configurações globais de ttk
        style.configure(
            ".",
            background=DarkTheme.SURFACE_0,
            foreground=DarkTheme.TEXT_MAIN,
            font=("Segoe UI", 10),
        )

        # Notebook (Abas)
        style.configure(
            "TNotebook",
            background=DarkTheme.BG_DARK,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=DarkTheme.SURFACE_1,
            foreground=DarkTheme.TEXT_MUTED,
            padding=[16, 8],
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", DarkTheme.SURFACE_0), ("active", DarkTheme.SURFACE_2)],
            foreground=[("selected", DarkTheme.ACCENT_PURPLE), ("active", DarkTheme.TEXT_MAIN)],
        )

        # Treeview (Tabela de Instâncias)
        style.configure(
            "Treeview",
            background=DarkTheme.SURFACE_1,
            foreground=DarkTheme.TEXT_MAIN,
            fieldbackground=DarkTheme.SURFACE_1,
            font=("Segoe UI", 10),
            rowheight=28,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=DarkTheme.SURFACE_2,
            foreground=DarkTheme.TEXT_MAIN,
            font=("Segoe UI", 10, "bold"),
            padding=[6, 6],
            borderwidth=0,
        )
        style.map(
            "Treeview.Heading",
            background=[("active", DarkTheme.SURFACE_HOVER)],
        )
        style.map(
            "Treeview",
            background=[("selected", DarkTheme.SURFACE_2)],
            foreground=[("selected", DarkTheme.ACCENT_PURPLE)],
        )

        # Scrollbars
        style.configure(
            "Vertical.TScrollbar",
            background=DarkTheme.SURFACE_1,
            troughcolor=DarkTheme.BG_DARK,
            arrowcolor=DarkTheme.TEXT_MUTED,
            borderwidth=0,
        )

    def _create_widgets(self):
        """Monta a estrutura visual da janela."""
        # Container Principal com padding
        main_container = tk.Frame(self.root, bg=DarkTheme.BG_DARK)
        main_container.pack(fill="both", expand=True, padx=16, pady=14)

        # ── 1. HEADER BAR ──
        self._build_header(main_container)

        # ── 2. CARDS DE MÉTRICAS (KPIs) ──
        self._build_metric_cards(main_container)

        # ── 3. PAINEL DE CONFIGURAÇÕES ──
        self._build_config_card(main_container)

        # ── 4. BARRA DE BOTÕES DE AÇÃO ──
        self._build_action_bar(main_container)

        # ── 5. ABAS: INSTÂNCIAS E CONSOLE DE LOGS ──
        self._build_tabs(main_container)

    def _build_header(self, parent):
        """Cabeçalho da aplicação."""
        header_frame = tk.Frame(parent, bg=DarkTheme.BG_DARK)
        header_frame.pack(fill="x", pady=(0, 10))

        # Título e Subtítulo
        title_box = tk.Frame(header_frame, bg=DarkTheme.BG_DARK)
        title_box.pack(side="left")

        title_lbl = tk.Label(
            title_box,
            text="Hunter Shiny",
            font=("Segoe UI", 16, "bold"),
            fg=DarkTheme.ACCENT_ORANGE,
            bg=DarkTheme.BG_DARK,
        )
        title_lbl.pack(anchor="w")

        self.lbl_subtitle = tk.Label(
            title_box,
            text="Pokémon Fire Red (US) v1.0 - Automação Multi-Instância mGBA",
            font=("Segoe UI", 9),
            fg=DarkTheme.TEXT_MUTED,
            bg=DarkTheme.BG_DARK,
        )
        self.lbl_subtitle.pack(anchor="w")

        # Status Badge no canto superior direito
        self.status_badge = tk.Label(
            header_frame,
            text="PRONTO",
            font=("Segoe UI", 10, "bold"),
            fg=DarkTheme.ACCENT_GREEN,
            bg=DarkTheme.SURFACE_1,
            padx=14,
            pady=6,
            relief="flat",
            bd=0,
        )
        self.status_badge.pack(side="right", pady=4)

    def _build_metric_cards(self, parent):
        """Cards de métricas em tempo real (KPIs)."""
        metrics_frame = tk.Frame(parent, bg=DarkTheme.BG_DARK)
        metrics_frame.pack(fill="x", pady=(0, 12))

        # Configura colunas proporcionais
        for i in range(5):
            metrics_frame.columnconfigure(i, weight=1, uniform="metric_cols")

        # 1. Tempo Decorrido
        self.lbl_elapsed_val = self._create_kpi_card(
            metrics_frame, col=0, title="TEMPO DECORRIDO", default_val="00:00:00", val_color=DarkTheme.ACCENT_BLUE
        )
        # 2. Instâncias Abertas / Ativas
        self.lbl_instances_val = self._create_kpi_card(
            metrics_frame, col=1, title="INSTÂNCIAS", default_val="0 / 10", val_color=DarkTheme.ACCENT_PURPLE
        )
        # 3. Total de Tentativas
        self.lbl_attempts_val = self._create_kpi_card(
            metrics_frame, col=2, title="TENTATIVAS", default_val="0", val_color=DarkTheme.ACCENT_YELLOW
        )
        # 4. Velocidade Estimada
        self.lbl_speed_val = self._create_kpi_card(
            metrics_frame, col=3, title="VELOCIDADE", default_val="0 / hora", val_color=DarkTheme.TEXT_MAIN
        )
        # 5. Probabilidade Acumulada
        self.lbl_chance_val = self._create_kpi_card(
            metrics_frame, col=4, title="CHANCE SHINY", default_val="0.00%", val_color=DarkTheme.ACCENT_GREEN
        )

    def _create_kpi_card(self, parent, col: int, title: str, default_val: str, val_color: str) -> tk.Label:
        """Cria um card de indicador visual moderno."""
        card = tk.Frame(
            parent,
            bg=DarkTheme.SURFACE_0,
            padx=12,
            pady=8,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        card.grid(row=0, column=col, sticky="nsew", padx=4)

        lbl_title = tk.Label(
            card,
            text=title,
            font=("Segoe UI", 8, "bold"),
            fg=DarkTheme.TEXT_DIM,
            bg=DarkTheme.SURFACE_0,
        )
        lbl_title.pack(anchor="center")

        lbl_val = tk.Label(
            card,
            text=default_val,
            font=("Segoe UI", 14, "bold"),
            fg=val_color,
            bg=DarkTheme.SURFACE_0,
        )
        lbl_val.pack(anchor="center", pady=(2, 0))
        return lbl_val

    def _build_config_card(self, parent):
        """Card retrátil/expansível com os campos de configuração da caçada."""
        card = tk.Frame(
            parent,
            bg=DarkTheme.SURFACE_0,
            padx=16,
            pady=12,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, 12))

        # Título da seção
        card_header = tk.Frame(card, bg=DarkTheme.SURFACE_0)
        card_header.pack(fill="x", pady=(0, 8))

        tk.Label(
            card_header,
            text="CONFIGURAÇÃO DA EXECUÇÃO",
            font=("Segoe UI", 9, "bold"),
            fg=DarkTheme.TEXT_MUTED,
            bg=DarkTheme.SURFACE_0,
        ).pack(side="left")

        # Grid de campos
        grid_frame = tk.Frame(card, bg=DarkTheme.SURFACE_0)
        grid_frame.pack(fill="x")
        grid_frame.columnconfigure(1, weight=1)

        # Linha 1: Emulador (mGBA.exe)
        tk.Label(
            grid_frame, text="Emulador mGBA:", font=("Segoe UI", 9), fg=DarkTheme.TEXT_MAIN, bg=DarkTheme.SURFACE_0
        ).grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))

        self.entry_mgba = tk.Entry(
            grid_frame,
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            insertbackground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        self.entry_mgba.grid(row=0, column=1, sticky="ew", pady=4, ipady=4, padx=(0, 8))

        btn_browse_mgba = tk.Button(
            grid_frame,
            text="Procurar...",
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_2,
            fg=DarkTheme.TEXT_MAIN,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._browse_mgba,
        )
        btn_browse_mgba.grid(row=0, column=2, sticky="e", pady=4)

        # Linha 2: ROM (.gba)
        tk.Label(
            grid_frame, text="Arquivo ROM (.gba):", font=("Segoe UI", 9), fg=DarkTheme.TEXT_MAIN, bg=DarkTheme.SURFACE_0
        ).grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))

        self.entry_rom = tk.Entry(
            grid_frame,
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            insertbackground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        self.entry_rom.grid(row=1, column=1, sticky="ew", pady=4, ipady=4, padx=(0, 8))

        btn_browse_rom = tk.Button(
            grid_frame,
            text="Procurar...",
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_2,
            fg=DarkTheme.TEXT_MAIN,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._browse_rom,
        )
        btn_browse_rom.grid(row=1, column=2, sticky="e", pady=4)

        # Linha 3: Save (.sav)
        tk.Label(
            grid_frame, text="Arquivo Save (.sav):", font=("Segoe UI", 9), fg=DarkTheme.TEXT_MAIN, bg=DarkTheme.SURFACE_0
        ).grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))

        self.entry_sav = tk.Entry(
            grid_frame,
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            insertbackground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        self.entry_sav.grid(row=2, column=1, sticky="ew", pady=4, ipady=4, padx=(0, 8))

        btn_browse_sav = tk.Button(
            grid_frame,
            text="Procurar...",
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_2,
            fg=DarkTheme.TEXT_MAIN,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._browse_sav,
        )
        btn_browse_sav.grid(row=2, column=2, sticky="e", pady=4)

        # Linha 4: Jogo Selecionado
        tk.Label(
            grid_frame, text="Jogo:", font=("Segoe UI", 9), fg=DarkTheme.TEXT_MAIN, bg=DarkTheme.SURFACE_0
        ).grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))

        game_frame = tk.Frame(grid_frame, bg=DarkTheme.SURFACE_0)
        game_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        self.var_game = tk.StringVar(value="firered")

        self.radio_game_fr = tk.Radiobutton(
            game_frame,
            text="Pokémon Fire Red",
            variable=self.var_game,
            value="firered",
            command=self._on_game_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_ORANGE,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_game_fr.pack(side="left", padx=(0, 16))

        self.radio_game_em = tk.Radiobutton(
            game_frame,
            text="Pokémon Emerald",
            variable=self.var_game,
            value="emerald",
            command=self._on_game_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_GREEN,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_game_em.pack(side="left", padx=(0, 10))

        # Linha 5: Alvo da Caçada / Inicial
        self.lbl_target_title = tk.Label(
            grid_frame, text="Alvo da Caçada:", font=("Segoe UI", 9), fg=DarkTheme.TEXT_MAIN, bg=DarkTheme.SURFACE_0
        )
        self.lbl_target_title.grid(row=4, column=0, sticky="w", pady=4, padx=(0, 8))

        target_container = tk.Frame(grid_frame, bg=DarkTheme.SURFACE_0)
        target_container.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)

        # Container de opções do Fire Red
        self.firered_target_frame = tk.Frame(target_container, bg=DarkTheme.SURFACE_0)
        self.var_firered_target = tk.StringVar(value="magikarp")

        self.radio_magi = tk.Radiobutton(
            self.firered_target_frame,
            text="Magikarp (Rota 4 - Slot Livre)",
            variable=self.var_firered_target,
            value="magikarp",
            command=self._on_firered_target_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_GREEN,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_magi.pack(side="left", padx=(0, 16))

        self.radio_char = tk.Radiobutton(
            self.firered_target_frame,
            text="Iniciais (Kanto - Slot 1)",
            variable=self.var_firered_target,
            value="starters",
            command=self._on_firered_target_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_ORANGE,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_char.pack(side="left", padx=(0, 10))

        # Container de opções do Emerald (Iniciais na bolsa do Prof. Birch)
        self.emerald_starter_frame = tk.Frame(target_container, bg=DarkTheme.SURFACE_0)
        self.var_emerald_starter = tk.StringVar(value="treecko")

        self.radio_treecko = tk.Radiobutton(
            self.emerald_starter_frame,
            text="Treecko (Planta - ◀ Esquerda)",
            variable=self.var_emerald_starter,
            value="treecko",
            command=self._on_emerald_starter_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_GREEN,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_treecko.pack(side="left", padx=(0, 14))

        self.radio_torchic = tk.Radiobutton(
            self.emerald_starter_frame,
            text="Torchic (Fogo - ● Centro)",
            variable=self.var_emerald_starter,
            value="torchic",
            command=self._on_emerald_starter_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_ORANGE,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_torchic.pack(side="left", padx=(0, 14))

        self.radio_mudkip = tk.Radiobutton(
            self.emerald_starter_frame,
            text="Mudkip (Água - ▶ Direita)",
            variable=self.var_emerald_starter,
            value="mudkip",
            command=self._on_emerald_starter_change,
            bg=DarkTheme.SURFACE_0,
            fg=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.radio_mudkip.pack(side="left", padx=(0, 10))

        # Inicialmente exibe o frame de Fire Red
        self.firered_target_frame.pack(side="left", fill="x")

        # Mantém compatibilidade com referências a self.var_target
        self.var_target = tk.StringVar(value="magikarp")

        # Linha 6: Quantidade de Instâncias e Porta
        extra_opts_frame = tk.Frame(grid_frame, bg=DarkTheme.SURFACE_0)
        extra_opts_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        # Quantidade de instâncias
        tk.Label(
            extra_opts_frame,
            text="Quantidade de Instâncias:",
            font=("Segoe UI", 9),
            fg=DarkTheme.TEXT_MAIN,
            bg=DarkTheme.SURFACE_0,
        ).pack(side="left", padx=(0, 6))

        self.spin_instances = tk.Spinbox(
            extra_opts_frame,
            from_=1,
            to=30,
            width=5,
            font=("Segoe UI", 9, "bold"),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.ACCENT_PURPLE,
            buttonbackground=DarkTheme.SURFACE_2,
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        self.spin_instances.pack(side="left", padx=(0, 20), ipady=2)

        # Porta TCP
        tk.Label(
            extra_opts_frame,
            text="Porta Servidor TCP:",
            font=("Segoe UI", 9),
            fg=DarkTheme.TEXT_MAIN,
            bg=DarkTheme.SURFACE_0,
        ).pack(side="left", padx=(0, 6))

        self.entry_port = tk.Entry(
            extra_opts_frame,
            width=8,
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            insertbackground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        self.entry_port.pack(side="left", padx=(0, 20), ipady=2)

        # Indicador de validação / alerta
        self.lbl_config_status = tk.Label(
            extra_opts_frame,
            text="",
            font=("Segoe UI", 8),
            fg=DarkTheme.ACCENT_RED,
            bg=DarkTheme.SURFACE_0,
        )
        self.lbl_config_status.pack(side="right")

    def _build_action_bar(self, parent):
        """Barra com botões de ação (Iniciar, Parar, Copiar Lua, Instruções)."""
        action_frame = tk.Frame(parent, bg=DarkTheme.BG_DARK)
        action_frame.pack(fill="x", pady=(0, 12))

        # Botão Iniciar Caçada
        self.btn_start = tk.Button(
            action_frame,
            text="INICIAR CAÇADA",
            font=("Segoe UI", 11, "bold"),
            bg=DarkTheme.ACCENT_GREEN,
            fg="#11111b",
            activebackground=DarkTheme.ACCENT_GREEN_HOVER,
            activeforeground="#11111b",
            relief="flat",
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.start_hunt,
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        # Botão Parar Caçada
        self.btn_stop = tk.Button(
            action_frame,
            text="PARAR CAÇADA",
            font=("Segoe UI", 11, "bold"),
            bg=DarkTheme.ACCENT_RED,
            fg="#11111b",
            activebackground=DarkTheme.ACCENT_RED_HOVER,
            activeforeground="#11111b",
            relief="flat",
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            state="disabled",
            command=self.stop_hunt,
        )
        self.btn_stop.pack(side="left", padx=(0, 15))

        # Botão Copiar Caminho do Script Lua
        self.btn_copy_lua = tk.Button(
            action_frame,
            text="Copiar Caminho do Script Lua",
            font=("Segoe UI", 9, "bold"),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._copy_lua_path,
        )
        self.btn_copy_lua.pack(side="left", padx=(0, 10))

        # Botão Como Usar / Instruções
        self.btn_help = tk.Button(
            action_frame,
            text="Como Usar / Instruções",
            font=("Segoe UI", 9),
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MUTED,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._show_instructions,
        )
        self.btn_help.pack(side="right")

    def _build_tabs(self, parent):
        """Abas com Tabela de Instâncias e Console de Logs."""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        # ── Aba 1: Tabela de Instâncias ──
        tab_instances = tk.Frame(notebook, bg=DarkTheme.SURFACE_0)
        notebook.add(tab_instances, text="  Instâncias  ")

        inst_container = tk.Frame(tab_instances, bg=DarkTheme.SURFACE_0, padx=8, pady=8)
        inst_container.pack(fill="both", expand=True)

        columns = ("id", "pid", "status", "attempts", "last_update")
        self.tree_instances = ttk.Treeview(
            inst_container,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree_instances.heading("id", text="Instância")
        self.tree_instances.heading("pid", text="PID mGBA")
        self.tree_instances.heading("status", text="Status")
        self.tree_instances.heading("attempts", text="Tentativas")
        self.tree_instances.heading("last_update", text="Última Atualização")

        self.tree_instances.column("id", width=90, anchor="center")
        self.tree_instances.column("pid", width=100, anchor="center")
        self.tree_instances.column("status", width=160, anchor="center")
        self.tree_instances.column("attempts", width=120, anchor="center")
        self.tree_instances.column("last_update", width=140, anchor="center")

        tree_scroll = ttk.Scrollbar(
            inst_container, orient="vertical", command=self.tree_instances.yview, style="Vertical.TScrollbar"
        )
        self.tree_instances.configure(yscrollcommand=tree_scroll.set)

        self.tree_instances.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Tags de cores para status na tabela
        self.tree_instances.tag_configure("shiny", foreground=DarkTheme.ACCENT_YELLOW, font=("Segoe UI", 10, "bold"))
        self.tree_instances.tag_configure("hunting", foreground=DarkTheme.ACCENT_GREEN)
        self.tree_instances.tag_configure("resetting", foreground=DarkTheme.ACCENT_BLUE)
        self.tree_instances.tag_configure("waiting", foreground=DarkTheme.TEXT_DIM)
        self.tree_instances.tag_configure("disconnected", foreground=DarkTheme.ACCENT_RED)

        # ── Aba 2: Console de Logs ──
        tab_logs = tk.Frame(notebook, bg=DarkTheme.SURFACE_0)
        notebook.add(tab_logs, text="  Console de Logs  ")

        log_container = tk.Frame(tab_logs, bg=DarkTheme.SURFACE_0, padx=8, pady=8)
        log_container.pack(fill="both", expand=True)

        # Toolbar do Log
        log_toolbar = tk.Frame(log_container, bg=DarkTheme.SURFACE_0)
        log_toolbar.pack(fill="x", pady=(0, 6))

        self.var_autoscroll = tk.BooleanVar(value=True)
        chk_autoscroll = tk.Checkbutton(
            log_toolbar,
            text="Rolar Automaticamente",
            variable=self.var_autoscroll,
            font=("Segoe UI", 8),
            fg=DarkTheme.TEXT_MUTED,
            bg=DarkTheme.SURFACE_0,
            activebackground=DarkTheme.SURFACE_0,
            activeforeground=DarkTheme.TEXT_MAIN,
            selectcolor=DarkTheme.SURFACE_1,
        )
        chk_autoscroll.pack(side="left")

        btn_clear_log = tk.Button(
            log_toolbar,
            text="Limpar Log",
            font=("Segoe UI", 8),
            bg=DarkTheme.SURFACE_2,
            fg=DarkTheme.TEXT_MUTED,
            activebackground=DarkTheme.SURFACE_HOVER,
            activeforeground=DarkTheme.TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._clear_log,
        )
        btn_clear_log.pack(side="right")

        # Text widget com scrollbar
        self.txt_log = tk.Text(
            log_container,
            bg=DarkTheme.SURFACE_1,
            fg=DarkTheme.TEXT_MAIN,
            font=("Consolas", 9),
            wrap="word",
            relief="flat",
            bd=0,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
            padx=8,
            pady=8,
        )
        log_scroll = ttk.Scrollbar(
            log_container, orient="vertical", command=self.txt_log.yview, style="Vertical.TScrollbar"
        )
        self.txt_log.configure(yscrollcommand=log_scroll.set)

        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # Configura tags coloridas para o log
        self.txt_log.tag_configure("INFO", foreground=DarkTheme.TEXT_MUTED)
        self.txt_log.tag_configure("SUCCESS", foreground=DarkTheme.ACCENT_GREEN)
        self.txt_log.tag_configure("WARNING", foreground=DarkTheme.ACCENT_YELLOW)
        self.txt_log.tag_configure("ERROR", foreground=DarkTheme.ACCENT_RED)
        self.txt_log.tag_configure("SHINY", foreground=DarkTheme.ACCENT_PURPLE, font=("Consolas", 10, "bold"))
        self.txt_log.tag_configure("TIMESTAMP", foreground=DarkTheme.TEXT_DIM)

        self.log("Aplicação iniciada com sucesso. Configure os caminhos e clique em Iniciar Caçada.", "INFO")

    # ── CARREGAMENTO E SALVAMENTO DE CONFIGURAÇÕES ──

    def _update_header_subtitle(self):
        """Atualiza o subtítulo com o jogo atual."""
        game = self.var_game.get()
        if hasattr(self, "lbl_subtitle"):
            if game == "emerald":
                self.lbl_subtitle.configure(
                    text="Pokémon Emerald (US) v1.0 - Automação Multi-Instância mGBA",
                    fg=DarkTheme.ACCENT_GREEN,
                )
            else:
                self.lbl_subtitle.configure(
                    text="Pokémon Fire Red (US) v1.0 - Automação Multi-Instância mGBA",
                    fg=DarkTheme.TEXT_MUTED,
                )

    def _update_target_frames_visibility(self):
        """Alterna a exibição dos seletores conforme o jogo escolhido."""
        game = self.var_game.get()
        self._update_header_subtitle()
        if game == "emerald":
            self.firered_target_frame.pack_forget()
            self.emerald_starter_frame.pack(side="left", fill="x")
            self.lbl_target_title.configure(text="Inicial Desejado:")
        else:
            self.emerald_starter_frame.pack_forget()
            self.firered_target_frame.pack(side="left", fill="x")
            self.lbl_target_title.configure(text="Alvo da Caçada:")

    def _populate_config_fields(self):
        """Insere as configurações nos campos da interface."""
        self.entry_mgba.delete(0, tk.END)
        self.entry_mgba.insert(0, self.config.mgba_path)

        self.entry_rom.delete(0, tk.END)
        self.entry_rom.insert(0, self.config.rom_path)

        self.entry_sav.delete(0, tk.END)
        self.entry_sav.insert(0, self.config.sav_path)

        game = getattr(self.config, "game", "firered")
        self.var_game.set(game)

        emerald_starter = getattr(self.config, "emerald_starter", "treecko")
        self.var_emerald_starter.set(emerald_starter)

        target = getattr(self.config, "target_pokemon", "magikarp")
        if target in ("treecko", "torchic", "mudkip"):
            self.var_emerald_starter.set(target)
            self.var_game.set("emerald")
            game = "emerald"
        elif target in ("charmander", "starters", "iniciais"):
            self.var_firered_target.set("starters")
            self.var_game.set("firered")
        else:
            self.var_firered_target.set("magikarp")

        self.var_target.set(target)
        self._update_target_frames_visibility()

        self.spin_instances.delete(0, tk.END)
        self.spin_instances.insert(0, str(self.config.num_instances))

        self.entry_port.delete(0, tk.END)
        self.entry_port.insert(0, str(self.config.server_port))

    def _read_config_from_fields(self) -> HuntConfig:
        """Lê os valores preenchidos na interface."""
        try:
            num_inst = int(self.spin_instances.get().strip())
        except ValueError:
            num_inst = 10

        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            port = 27015

        game = self.var_game.get()
        emerald_starter = self.var_emerald_starter.get()
        if game == "emerald":
            target = emerald_starter
        else:
            target = self.var_firered_target.get()

        lua_path = str(self._get_active_lua_path())

        return HuntConfig(
            mgba_path=self.entry_mgba.get().strip(),
            rom_path=self.entry_rom.get().strip(),
            sav_path=self.entry_sav.get().strip(),
            num_instances=num_inst,
            server_port=port,
            lua_script_path=lua_path,
            target_pokemon=target,
            game=game,
            emerald_starter=emerald_starter,
        )

    def _get_active_lua_path(self) -> Path:
        """Retorna o caminho do script Lua correspondente à configuração atual."""
        game = self.var_game.get()
        if game == "emerald":
            return EMERALD_LUA_PATH
        target = self.var_firered_target.get()
        if target == "magikarp":
            return MAGIKARP_LUA_PATH
        return DEFAULT_LUA_PATH

    # ── NAVEGAÇÃO DE ARQUIVOS (FILE DIALOGS) E EVENTOS DE ALVO ──

    def _on_game_change(self):
        """Callback ao alternar entre Pokémon Fire Red e Pokémon Emerald."""
        game = self.var_game.get()
        self._update_target_frames_visibility()

        if game == "emerald":
            starter = self.var_emerald_starter.get()
            self.var_target.set(starter)
            self.log(f"Jogo alterado para: Pokémon Emerald | Inicial: {starter.capitalize()} | Script: iniciais_emerald.lua", "INFO")
        else:
            target = self.var_firered_target.get()
            self.var_target.set(target)
            if target == "magikarp":
                self.log("Jogo alterado para: Pokémon Fire Red | Alvo: Magikarp | Script: shiny_magi.lua", "INFO")
            else:
                self.log("Jogo alterado para: Pokémon Fire Red | Alvo: Iniciais de Kanto | Script: shiny_hunt.lua", "INFO")

    def _on_emerald_starter_change(self):
        """Callback ao selecionar um dos iniciais de Hoenn (Emerald)."""
        starter = self.var_emerald_starter.get()
        self.var_target.set(starter)

        # Atualiza imediatamente TARGET_STARTER no arquivo iniciais_emerald.lua raiz e em dist (idênticos)
        try:
            starter_val = starter.strip().lower()
            if EMERALD_LUA_PATH.exists():
                import re
                txt = EMERALD_LUA_PATH.read_text(encoding="utf-8")
                txt = re.sub(
                    r'local TARGET_STARTER\s*=\s*.*',
                    f'local TARGET_STARTER = "{starter_val}"',
                    txt
                )
                EMERALD_LUA_PATH.write_text(txt, encoding="utf-8")
                dist_lua = EMERALD_LUA_PATH.parent / "dist" / "iniciais_emerald.lua"
                if dist_lua.exists():
                    dist_lua.write_text(txt, encoding="utf-8")
            (EMERALD_LUA_PATH.parent / "emerald_starter.txt").write_text(f"{starter_val}\n", encoding="utf-8")
        except Exception:
            pass

        names = {
            "treecko": "Treecko (Planta - Seta Esquerda ◀)",
            "torchic": "Torchic (Fogo - Centro ●)",
            "mudkip": "Mudkip (Água - Seta Direita ▶)",
        }
        self.log(f"Inicial de Emerald selecionado: {names.get(starter, starter.capitalize())} | Script: iniciais_emerald.lua", "INFO")

    def _on_firered_target_change(self):
        """Callback ao alterar o alvo de Fire Red."""
        target = self.var_firered_target.get()
        self.var_target.set(target)
        if target == "magikarp":
            self.log("Alvo de Fire Red: Magikarp (Rota 4 - Slot Livre) | Script: shiny_magi.lua", "INFO")
        else:
            self.log("Alvo de Fire Red: Iniciais de Kanto (Slot 1) | Script: shiny_hunt.lua", "INFO")

    def _on_target_change(self):
        """Compatibilidade retroativa."""
        if self.var_game.get() == "emerald":
            self._on_emerald_starter_change()
        else:
            self._on_firered_target_change()

    def _browse_mgba(self):
        """Seleciona o executável do mGBA."""
        current = self.entry_mgba.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).parent.exists() else r"C:\Program Files\mGBA"
        path = filedialog.askopenfilename(
            title="Selecione o executável do mGBA",
            initialdir=initial_dir,
            filetypes=[("Executável mGBA", "mGBA.exe"), ("Executáveis (*.exe)", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self.entry_mgba.delete(0, tk.END)
            self.entry_mgba.insert(0, str(Path(path).resolve()))

    def _browse_rom(self):
        """Seleciona o arquivo da ROM e auto-preenche o Save se existir."""
        current = self.entry_rom.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).parent.exists() else r"C:\roms"
        game_name = "Pokémon Emerald" if self.var_game.get() == "emerald" else "Pokémon Fire Red"
        path = filedialog.askopenfilename(
            title=f"Selecione a ROM de {game_name} (.gba)",
            initialdir=initial_dir,
            filetypes=[("ROM Game Boy Advance (*.gba)", "*.gba"), ("Todos os arquivos", "*.*")],
        )
        if path:
            rom_path = Path(path).resolve()
            self.entry_rom.delete(0, tk.END)
            self.entry_rom.insert(0, str(rom_path))

            name_lower = rom_path.name.lower()
            if "emerald" in name_lower:
                self.var_game.set("emerald")
                self._update_target_frames_visibility()
                self._on_game_change()
            elif "firered" in name_lower or "fire_red" in name_lower:
                self.var_game.set("firered")
                self._update_target_frames_visibility()
                self._on_game_change()

            # Sugere automaticamente o Save correspondente na mesma pasta
            suggested_sav = rom_path.with_suffix(".sav")
            if suggested_sav.exists() and not self.entry_sav.get().strip():
                self.entry_sav.delete(0, tk.END)
                self.entry_sav.insert(0, str(suggested_sav))

    def _browse_sav(self):
        """Seleciona o arquivo de Save."""
        current = self.entry_sav.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).parent.exists() else r"C:\roms"
        path = filedialog.askopenfilename(
            title="Selecione o arquivo de Save (.sav)",
            initialdir=initial_dir,
            filetypes=[("Arquivo de Save (*.sav)", "*.sav"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self.entry_sav.delete(0, tk.END)
            self.entry_sav.insert(0, str(Path(path).resolve()))

    def _copy_lua_path(self):
        """Copia o caminho do script Lua para a área de transferência e pré-registra no mGBA (qt.ini)."""
        lua_target = self._get_active_lua_path().resolve()
        lua_name = lua_target.name

        # Registra no histórico do mGBA e copia para a área de transferência
        register_mgba_recent_script(lua_target)
        copy_to_clipboard(str(lua_target))
        self.root.clipboard_clear()
        self.root.clipboard_append(str(lua_target))

        self.log(f"Script ({lua_name}) pré-registrado no histórico do mGBA e copiado para o Clipboard!", "SUCCESS")
        messagebox.showinfo(
            "Script Pré-configurado!",
            f"O script '{lua_name}' foi configurado no histórico do mGBA e seu caminho foi copiado!\n\n"
            f"Caminho:\n{lua_target}\n\n"
            f"COMO CARREGAR NAS JANELAS DO mGBA:\n\n"
            f"• MÉTODO 1 (1 CLIQUE - Mais Rápido!):\n"
            f"  Menu Tools > Scripting > File > Recent scripts > clique no 1º item ({lua_name})!\n\n"
            f"• MÉTODO 2 (Direto com Teclado):\n"
            f"  Menu Tools > Scripting > aperte Ctrl+O e dê Ctrl+V para colar o caminho!",
        )

    def _show_instructions(self):
        """Exibe popup com passo a passo ilustrado."""
        lua_path = self._get_active_lua_path()
        lua_name = lua_path.name
        game = self.var_game.get()

        if game == "emerald":
            starter = self.var_emerald_starter.get()
            names = {
                "treecko": "Treecko (Planta - Seta Esquerda ◀)",
                "torchic": "Torchic (Fogo - Centro ●)",
                "mudkip": "Mudkip (Água - Seta Direita ▶)",
            }
            target_info = (
                f"COMO PREPARAR O JOGO (POKÉMON EMERALD — INICIAL: {starter.upper()}):\n"
                "• No jogo, fique na Rota 101 em frente à BOLSA do Prof. Birch (quando atacado pelo Zigzagoon).\n"
                "• Sua party deve estar vazia (0 Pokémon na equipe).\n"
                "• Salve o jogo pelo menu (Start > Save) exatamente nessa posição.\n"
                f"• Inicial selecionado: {names.get(starter, starter.capitalize())}.\n"
                "• O script abrirá a bolsa, moverá o cursor com as setas até o inicial escolhido,\n"
                "  confirmará com o botão A e verificará o XOR de Shiny no Slot 1!\n\n"
            )
        else:
            target = self.var_firered_target.get()
            if target == "magikarp":
                target_info = (
                    "COMO PREPARAR O JOGO (POKÉMON FIRE RED — MAGIKARP):\n"
                    "• Posicione o personagem em frente ao vendedor no Centro Pokémon da Rota 4.\n"
                    "• Tenha pelo menos 1 slot livre na sua party e pelo menos 500 moedas.\n"
                    "• Salve o jogo pelo menu (Start > Save) exatamente nessa posição.\n\n"
                )
            else:
                target_info = (
                    "COMO PREPARAR O JOGO (POKÉMON FIRE RED — INICIAIS DE KANTO):\n"
                    "• Posicione o personagem em frente à Pokébola do inicial desejado (Bulbasaur, Charmander ou Squirtle) no laboratório do Prof. Carvalho.\n"
                    "• Party com 0 Pokémon (Slot 1 livre).\n"
                    "• Salve o jogo pelo menu (Start > Save) exatamente nessa posição.\n\n"
                )

        msg = (
            f"{target_info}"
            "COMO CARREGAR O SCRIPT LUA NAS JANELAS:\n\n"
            "1. Clique em 'INICIAR CAÇADA'. O programa abrirá as janelas do mGBA, configurará o histórico do emulador e copiará o caminho para o seu Clipboard!\n\n"
            "2. Para CADA janela do mGBA aberta:\n"
            f"   • MÉTODO RÁPIDO (1 CLIQUE):\n"
            f"     No menu: Tools > Scripting... > File > Recent scripts > clique em {lua_name}!\n\n"
            f"   • MÉTODO DIRETO COM TECLADO:\n"
            f"     No menu: Tools > Scripting... > aperte Ctrl+O e depois Ctrl+V (o caminho já está copiado)!\n\n"
            "3. O script conecta automaticamente e a caçada começa!\n"
            "4. Quando o Shiny for encontrado, o programa salvará no Slot 1 e fechará as outras instâncias automaticamente."
        )
        messagebox.showinfo("Instruções de Uso", msg)

    # ── LOGGING ──

    def log(self, message: str, level: str = "INFO"):
        """Adiciona mensagem formatada ao console interno de logs."""
        timestamp = datetime.now().strftime("[%H:%M:%S] ")
        self.txt_log.configure(state="normal")
        self.txt_log.insert(tk.END, timestamp, "TIMESTAMP")
        self.txt_log.insert(tk.END, f"[{level}] ", level)
        self.txt_log.insert(tk.END, f"{message}\n")

        if self.var_autoscroll.get():
            self.txt_log.see(tk.END)
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        """Limpa o console de logs."""
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.configure(state="disabled")

    # ── CONTROLE DA CAÇADA (START / STOP) ──

    def start_hunt(self):
        """Valida e inicia a caçada em uma thread de suporte."""
        if self.is_hunting:
            return

        # Lê e valida configurações
        config = self._read_config_from_fields()
        errors = config.validate()
        if errors:
            self.lbl_config_status.config(text="Erro de validação!")
            messagebox.showerror("Erro de Configuração", "\n".join(errors))
            return

        self.lbl_config_status.config(text="")
        self.config = config
        self.config.save()  # Salva para as próximas execuções

        # Pré-configura o script atual no histórico [recentScripts] do mGBA (qt.ini)
        # e copia o caminho completo para a Área de Transferência
        try:
            target_lua = Path(self.config.lua_script_path).resolve()
            register_mgba_recent_script(target_lua)
            copy_to_clipboard(str(target_lua))
            self.root.clipboard_clear()
            self.root.clipboard_append(str(target_lua))
        except Exception:
            pass

        # Atualiza botões e status visual
        self.is_hunting = True
        self.shiny_celebrated = False
        self.start_time = datetime.now()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.spin_instances.config(state="disabled")
        self.entry_mgba.config(state="disabled")
        self.entry_rom.config(state="disabled")
        self.entry_sav.config(state="disabled")
        self.entry_port.config(state="disabled")
        self.radio_magi.config(state="disabled")
        self.radio_char.config(state="disabled")

        self.status_badge.config(text="CAÇANDO", fg=DarkTheme.ACCENT_GREEN)
        self.lbl_instances_val.config(text=f"0 / {self.config.num_instances}")
        self.lbl_attempts_val.config(text="0")
        self.lbl_speed_val.config(text="0 / hora")
        self.lbl_chance_val.config(text="0.00%")

        # Limpa tabela de instâncias e popula com os slots
        for item in self.tree_instances.get_children():
            self.tree_instances.delete(item)
        self.pid_map.clear()

        for i in range(1, self.config.num_instances + 1):
            self.tree_instances.insert(
                "",
                "end",
                iid=f"inst_{i}",
                values=(f"#{i}", "Iniciando...", "Aguardando Lua", "0", "-"),
                tags=("waiting",),
            )

        self.log(f"Iniciando preparação de {self.config.num_instances} instâncias...", "INFO")

        # Inicia thread em background para não travar o GUI
        threading.Thread(target=self._hunt_runner_thread, daemon=True).start()

    def _hunt_runner_thread(self):
        """Thread que executa o setup, inicia o servidor TCP e lança o mGBA."""
        try:
            self.manager = InstanceManager(self.config)

            # 1. Setup dos diretórios e cópias
            self.event_queue.put(("log", ("Copiando arquivos da ROM e SAV para cada instância...", "INFO")))
            self.manager.setup_instances()
            self.event_queue.put(("log", ("Diretórios de instâncias prontos.", "SUCCESS")))

            # 2. Servidor TCP
            self.server = ShinyServer(
                port=self.config.server_port,
                max_instances=self.config.num_instances,
                on_event=self._on_server_event,
            )
            self.server.start()
            self.event_queue.put(
                ("log", (f"Servidor TCP ativo na porta {self.config.server_port}. Aguardando conexões...", "SUCCESS"))
            )

            # 3. Lançamento dos mGBAs
            self.event_queue.put(("log", ("Abrindo instâncias do mGBA...", "INFO")))

            def on_proc_launch(inst_idx: int, pid: int):
                self.event_queue.put(("proc_launched", (inst_idx, pid)))

            self.manager.launch_instances(on_launch=on_proc_launch)
            alive = self.manager.alive_count()
            self.event_queue.put(("log", (f"{alive} janelas do mGBA abertas com sucesso!", "SUCCESS")))
            lua_filename = Path(self.config.lua_script_path).name
            self.event_queue.put((
                "log",
                (f"DICA RÁPIDA: '{lua_filename}' já está no topo de 'Recent scripts' e no seu Clipboard!", "SUCCESS"),
            ))
            self.event_queue.put((
                "log",
                ("Nas janelas: Tools > Scripting > File > Recent scripts (ou Ctrl+O > Ctrl+V > Enter).", "WARNING"),
            ))

        except Exception as e:
            self.event_queue.put(("hunt_error", str(e)))

    def _on_server_event(self, event_type: str, data: dict):
        """Callback thread-safe vindo do ShinyServer."""
        self.event_queue.put(("server_event", (event_type, data)))

    def _process_event_queue(self):
        """Consome eventos da fila na thread principal do Tkinter."""
        try:
            while True:
                msg_type, payload = self.event_queue.get_nowait()

                if msg_type == "log":
                    text, level = payload
                    self.log(text, level)

                elif msg_type == "proc_launched":
                    inst_idx, pid = payload
                    self.pid_map[inst_idx] = pid
                    iid = f"inst_{inst_idx}"
                    if self.tree_instances.exists(iid):
                        curr = list(self.tree_instances.item(iid, "values"))
                        curr[1] = str(pid)
                        self.tree_instances.item(iid, values=curr)

                elif msg_type == "hunt_error":
                    error_msg = payload
                    self.log(f"Erro na caçada: {error_msg}", "ERROR")
                    messagebox.showerror("Erro na Execução", error_msg)
                    self.stop_hunt()

                elif msg_type == "server_event":
                    event_type, data = payload
                    self._handle_server_event(event_type, data)

        except queue.Empty:
            pass

        # Reagenda verificação a cada 50ms
        self.root.after(50, self._process_event_queue)

    def _handle_server_event(self, event_type: str, data: dict):
        """Trata eventos de rede do servidor de caçada."""
        if event_type == "client_connected":
            client_id = data.get("client_id", 0)
            conn_count = data.get("connected_count", 0)
            self.lbl_instances_val.config(text=f"{conn_count} / {self.config.num_instances}")
            self.log(f"Instância #{client_id} conectou-se ao servidor.", "INFO")

            iid = f"inst_{client_id}"
            if self.tree_instances.exists(iid):
                curr = list(self.tree_instances.item(iid, "values"))
                curr[2] = "Conectado"
                curr[4] = datetime.now().strftime("%H:%M:%S")
                self.tree_instances.item(iid, values=curr, tags=("hunting",))

        elif event_type == "client_disconnected":
            client_id = data.get("client_id", 0)
            conn_count = data.get("connected_count", 0)
            self.lbl_instances_val.config(text=f"{conn_count} / {self.config.num_instances}")
            self.log(f"Instância #{client_id} desconectou-se.", "WARNING")

            iid = f"inst_{client_id}"
            if self.tree_instances.exists(iid):
                curr = list(self.tree_instances.item(iid, "values"))
                curr[2] = "Desconectado"
                curr[4] = datetime.now().strftime("%H:%M:%S")
                self.tree_instances.item(iid, values=curr, tags=("disconnected",))

        elif event_type == "attempt_update":
            client_id = data.get("client_id", 0)
            inst_attempts = data.get("instance_attempts", 0)
            total_attempts = data.get("total_attempts", 0)

            self.lbl_attempts_val.config(text=f"{total_attempts:,}")
            chance = calculate_shiny_chance(total_attempts)
            self.lbl_chance_val.config(text=f"{chance:.2f}%")

            iid = f"inst_{client_id}"
            if self.tree_instances.exists(iid):
                curr = list(self.tree_instances.item(iid, "values"))
                curr[2] = "Caçando"
                curr[3] = str(inst_attempts)
                curr[4] = datetime.now().strftime("%H:%M:%S")
                self.tree_instances.item(iid, values=curr, tags=("hunting",))

        elif event_type == "instance_update":
            client_id = data.get("client_id", 0)
            status = data.get("status", "")
            iid = f"inst_{client_id}"
            if self.tree_instances.exists(iid):
                curr = list(self.tree_instances.item(iid, "values"))
                curr[2] = status.capitalize()
                curr[4] = datetime.now().strftime("%H:%M:%S")
                tag = "resetting" if status == "resetando" else "hunting"
                self.tree_instances.item(iid, values=curr, tags=(tag,))

        elif event_type == "shiny_found":
            self._handle_shiny_celebration(data)

    def _handle_shiny_celebration(self, info: dict):
        """Celebra a descoberta do Shiny com som, log e janela especial."""
        # Marca que o shiny foi celebrado para impedir que _tick_timer
        # chame stop_hunt() ao detectar que os processos mGBA foram fechados
        self.shiny_celebrated = True

        inst_num = info.get("instance", "?")
        pv = info.get("pv", "?")
        otid = info.get("otid", "?")
        total_att = info.get("total_attempts", "?")
        inst_att = info.get("attempts_this_instance", "?")
        elapsed = format_elapsed(self.start_time)

        # Atualiza badge de status
        self.status_badge.config(text="SHINY ENCONTRADO!", fg="#11111b", bg=DarkTheme.ACCENT_YELLOW)

        # Identifica a instância correta pelo save state gravado em disco
        keep_idx = None
        if self.manager:
            keep_idx = self.manager.find_shiny_instance(self.server.start_time)
            if keep_idx is not None:
                info["dir_instance"] = keep_idx
                # Sincroniza a instância do info se houver divergência
                if str(inst_num) != str(keep_idx):
                    self.log(
                        f"Sincronização de Instância: script reportou #{inst_num}, "
                        f"mas o save state foi confirmado na Instância #{keep_idx}. "
                        f"Associando para #{keep_idx}.",
                        "WARNING",
                    )
                    inst_num = keep_idx
                    info["instance"] = keep_idx

        # Se não detectou save state por timestamp mas tem inst_num numérico, usa inst_num
        if keep_idx is None and isinstance(inst_num, int):
            keep_idx = inst_num
            info["dir_instance"] = inst_num

        # Destaca a linha correspondente na tabela
        iid = f"inst_{inst_num}"
        if self.tree_instances.exists(iid):
            curr = list(self.tree_instances.item(iid, "values"))
            curr[2] = "SHINY!"
            curr[4] = datetime.now().strftime("%H:%M:%S")
            self.tree_instances.item(iid, values=curr, tags=("shiny",))

        self.log("=" * 60, "SHINY")
        self.log(f"SHINY ENCONTRADO NA INSTÂNCIA #{inst_num}!", "SHINY")
        self.log(f"Personality Value (PV): {pv} | OT ID: {otid}", "SHINY")
        self.log(f"Tentativas: {inst_att} (desta instância) | Total acumulado: {total_att}", "SHINY")
        self.log(f"Tempo total decorrido: {elapsed}", "SHINY")
        self.log("=" * 60, "SHINY")

        # Fecha as outras instâncias em background para não bloquear o Tkinter
        # (kill_all contém time.sleep que travaria o event loop)
        if self.manager:
            if keep_idx is None:
                # Não sabemos qual é: é mais seguro NÃO fechar nada.
                self.log(
                    "Não foi possível identificar qual janela achou o shiny. "
                    "Nenhuma janela foi fechada. Procure o .ss1 mais recente em instances/.",
                    "WARNING",
                )
            else:
                threading.Thread(
                    target=self.manager.kill_all,
                    args=(keep_idx,),
                    daemon=True,
                ).start()

        # Tenta tocar som de notificação do Windows
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

        # Exibe modal de celebração
        self._show_celebration_dialog(info, elapsed)

    def _show_celebration_dialog(self, info: dict, elapsed: str):
        """Abre janela de celebração com detalhes do Shiny."""
        win = tk.Toplevel(self.root)
        win.title("SHINY ENCONTRADO!")
        win.geometry("540x420")
        win.configure(bg=DarkTheme.BG_DARK)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        content = tk.Frame(win, bg=DarkTheme.BG_DARK, padx=20, pady=20)
        content.pack(fill="both", expand=True)

        tk.Label(
            content,
            text="PARABÉNS! SHINY ENCONTRADO!",
            font=("Segoe UI", 16, "bold"),
            fg=DarkTheme.ACCENT_YELLOW,
            bg=DarkTheme.BG_DARK,
        ).pack(pady=(0, 10))

        details_frame = tk.Frame(
            content,
            bg=DarkTheme.SURFACE_0,
            padx=16,
            pady=16,
            highlightbackground=DarkTheme.SURFACE_2,
            highlightthickness=1,
        )
        details_frame.pack(fill="x", pady=10)

        inst_num = info.get("instance", "?")
        pv = info.get("pv", "?")
        otid = info.get("otid", "?")
        total = info.get("total_attempts", "?")

        game_display = "Pokémon Emerald" if self.var_game.get() == "emerald" else "Pokémon Fire Red"
        target_display = self.var_emerald_starter.get().capitalize() if self.var_game.get() == "emerald" else (
            "Magikarp" if self.var_firered_target.get() == "magikarp" else "Inicial de Kanto"
        )

        rows = [
            ("Jogo:", game_display),
            ("Pokémon Alvo:", target_display),
            ("Instância Vencedora:", f"#{inst_num}"),
            ("Personality Value (PV):", str(pv)),
            ("OT ID do Treinador:", str(otid)),
            ("Total de Tentativas:", f"{total:,}" if isinstance(total, int) else str(total)),
            ("Tempo Total Decorrido:", elapsed),
        ]

        for label, val in rows:
            r_frame = tk.Frame(details_frame, bg=DarkTheme.SURFACE_0)
            r_frame.pack(fill="x", pady=2)
            tk.Label(
                r_frame, text=label, font=("Segoe UI", 9, "bold"), fg=DarkTheme.TEXT_MUTED, bg=DarkTheme.SURFACE_0
            ).pack(side="left")
            tk.Label(
                r_frame, text=val, font=("Segoe UI", 10, "bold"), fg=DarkTheme.ACCENT_GREEN, bg=DarkTheme.SURFACE_0
            ).pack(side="right")

        dir_inst = info.get("dir_instance", inst_num)
        tk.Label(
            content,
            text=(
                f"O Save State foi salvo no SLOT 1 da Instância #{dir_inst}.\n"
                "Para continuar jogando:\n"
                "1. Vá na janela do mGBA que ficou aberta.\n"
                "2. Menu File > Load State > Slot 1."
            ),
            font=("Segoe UI", 9),
            fg=DarkTheme.TEXT_MAIN,
            bg=DarkTheme.BG_DARK,
            justify="center",
        ).pack(pady=10)

        btn_ok = tk.Button(
            content,
            text="Entendido!",
            font=("Segoe UI", 10, "bold"),
            bg=DarkTheme.ACCENT_YELLOW,
            fg="#11111b",
            relief="flat",
            bd=0,
            padx=20,
            pady=6,
            cursor="hand2",
            command=win.destroy,
        )
        btn_ok.pack(pady=(5, 0))

    def stop_hunt(self):
        """Interrompe a caçada e finaliza os processos do mGBA."""
        if not self.is_hunting:
            return

        self.log("Encerrando caçada e fechando instâncias do mGBA...", "WARNING")

        # Executa kill_all em background para não bloquear o Tkinter
        if self.manager:
            def _kill_background():
                try:
                    self.manager.kill_all()
                except Exception:
                    pass
            threading.Thread(target=_kill_background, daemon=True).start()

        if self.server:
            try:
                self.server.stop()
            except Exception:
                pass

        self.is_hunting = False
        self.shiny_celebrated = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.spin_instances.config(state="normal")
        self.entry_mgba.config(state="normal")
        self.entry_rom.config(state="normal")
        self.entry_sav.config(state="normal")
        self.entry_port.config(state="normal")
        self.radio_magi.config(state="normal")
        self.radio_char.config(state="normal")

        self.status_badge.config(text="PARADO", fg=DarkTheme.ACCENT_RED, bg=DarkTheme.SURFACE_1)
        self.log("Caçada encerrada.", "INFO")

    def _tick_timer(self):
        """Atualiza o relógio a cada segundo e calcula a velocidade média."""
        if self.is_hunting and self.start_time:
            # 1. Atualiza Tempo Decorrido
            elapsed_str = format_elapsed(self.start_time)
            self.lbl_elapsed_val.config(text=elapsed_str)

            # 2. Atualiza contagem de instâncias do mGBA vivas
            if self.manager:
                alive = self.manager.alive_count()
                self.lbl_instances_val.config(text=f"{alive} / {self.config.num_instances}")

                # Se todos os processos foram fechados externamente pelo usuário
                # Não chamar stop_hunt se um shiny foi encontrado (a celebração está em andamento)
                if alive == 0 and len(self.manager.processes) > 0 and not self.shiny_celebrated and not (self.server and self.server.shiny_found):
                    self.log("Todas as janelas do mGBA foram fechadas.", "WARNING")
                    self.stop_hunt()

            # 3. Calcula velocidade de tentativas por hora
            if self.server:
                total_att = self.server.total_attempts
                elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
                if elapsed_seconds > 5 and total_att > 0:
                    speed_per_hour = int((total_att / elapsed_seconds) * 3600)
                    self.lbl_speed_val.config(text=f"~{speed_per_hour:,} / h")

        self.root.after(1000, self._tick_timer)

    def on_close_window(self):
        """Confirmação de fechamento da aplicação e cleanup seguro."""
        if self.is_hunting:
            ans = messagebox.askyesno(
                "Caçada em Andamento",
                "A caçada está em andamento. Deseja fechar o programa e encerrar todas as instâncias do mGBA?",
            )
            if not ans:
                return
            self.stop_hunt()

        # Salva as últimas configurações usadas
        try:
            cfg = self._read_config_from_fields()
            cfg.save()
        except Exception:
            pass

        self.root.destroy()


def main():
    root = tk.Tk()
    app = ShinyHuntGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
