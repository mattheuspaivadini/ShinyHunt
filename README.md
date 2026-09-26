# Hunter Shiny

[Português](#português) | [English](#english)

---

## Português

Automação para caça de Pokémon Shiny em Pokémon Fire Red (US) v1.0 e Pokémon Emerald (US) v1.0 utilizando instâncias simultâneas do mGBA coordenadas via socket TCP.

### Recursos Recentes

- **Suporte a Pokémon Emerald:** Caçada automatizada dos iniciais de Hoenn (**Treecko**, **Torchic** e **Mudkip**) com o script `iniciais_emerald.lua`.
- **Navegação Inteligente na Bolsa do Prof. Birch:** O script interage com a bolsa na Rota 101, move as setas até o inicial escolhido na interface (Treecko = ◀ Esquerda, Torchic = ● Centro, Mudkip = ▶ Direita), confirma com A e lê a memória do Slot 1 (`0x020244EC`).
- **Alternador de Jogos no App:** Seleção rápida entre Pokémon Fire Red e Pokémon Emerald diretamente pela interface gráfica ou linha de comando.
- **Anti-determinismo de RNG:** Variação dinâmica de frames e sementes estocásticas por instância — vital especialmente para Emerald, cujo PRNG inicia em zero no boot.
- **Ciclos mais rápidos:** Ciclos otimizados (~16 a 20s por tentativa).
- **Detecção de Save State:** Identificação da instância vencedora por data de modificação do arquivo `.ss1`, mantendo apenas a janela vitoriosa aberta.

### Pré-requisitos

| Item | Especificação |
|---|---|
| Sistema | Windows 10/11 (64-bit) |
| Emulador | mGBA v0.10+ instalado |
| ROMs Compatíveis | Pokémon Fire Red (US) v1.0 / Pokémon Emerald (US) v1.0 |
| Save | Arquivo `.sav` salvo em frente à Pokébola desejada (Fire Red) ou em frente à Bolsa do Prof. Birch (Emerald) |
| Python | 3.10+ |

### Como Usar

#### 1. Preparação do Save
Posicione o personagem em frente à Pokébola do Pokémon inicial escolhido (Charmander, Squirtle ou Bulbasaur) no laboratório do Professor Carvalho, virado para ela e pronto para interagir. Salve o jogo pelo menu e feche o emulador.

#### 2. Execução

```powershell
# Interface Gráfica (Recomendado)
python shiny_hunter.py

# Linha de Comando (CLI)
python shiny_hunter.py --cli
```

#### 3. Configuração
Na interface gráfica:
1. Defina o caminho do executável do mGBA.
2. Defina os caminhos da ROM (`.gba`) e do Save (`.sav`).
3. Ajuste a quantidade de instâncias desejada (padrão: 10).
4. Clique em **Iniciar Caçada**.

#### 4. Carregar o Script Lua
Em cada janela aberta do mGBA:
1. Acesse **Tools** > **Scripting...**
2. Clique em **File** > **Load script...**
3. Selecione o arquivo `shiny_hunt.lua`.

*Dica: o Fast-Forward do mGBA pode ser usado para acelerar a velocidade da emulação.*

#### 5. Finalização
Quando um shiny for detectado:
1. A janela que encontrou o shiny salvará o estado no **Slot 1** (`.ss1`).
2. As demais instâncias receberão comando de parada e serão fechadas.
3. A janela com o shiny permanecerá aberta com os dados (PID e OTID) exibidos na tela.

### Rendimento Estimado

| Modo | Tempo por Tentativa | Rendimento (10 instâncias) | Tempo Estimado (1/8192) |
|---|:---:|:---:|:---:|
| Normal (60 FPS) | ~20,5 s | ~1.750 tent./h | ~4,7 horas |
| Fast-Forward (4x) | ~5,0 s | ~7.000 tent./h | ~1,2 horas |

### Estrutura do Projeto

```text
ShinyHunt/
├── shiny_core.py
├── shiny_hunter.py
├── shiny_hunter_gui.py
├── shiny_hunt.lua           # Iniciais de Kanto (Fire Red)
├── shiny_magi.lua           # Magikarp Rota 4 (Fire Red)
├── iniciais_emerald.lua     # Iniciais de Hoenn (Emerald)
├── config.json
└── README.md
```

### Especificações Técnicas de Memória

#### Pokémon Fire Red (US) v1.0 (BPRE)
- **Party Slot 1 (PV/PID):** `0x02024284` (u32)
- **Trainer ID / Secret ID (OTID):** `0x02024288` (u32)

#### Pokémon Emerald (US) v1.0 (BPEE)
- **Party Slot 1 (PV/PID):** `0x020244EC` (u32)
- **Trainer ID / Secret ID (OTID):** `0x020244F0` (u32)

Fórmula Shiny (Gen 3):
```text
TID = OTID & 0xFFFF
SID = (OTID >> 16) & 0xFFFF
P1  = (PV >> 16) & 0xFFFF
P2  = PV & 0xFFFF

Shiny se: (P1 XOR P2 XOR TID XOR SID) < 8
```

### Solução de Problemas

- **Script Lua em modo standalone:** Inicie o servidor Python antes de carregar o script no mGBA.
- **Aviso de PV inicial não-zero:** O save utilizado já contém um Pokémon na equipe. Use um save anterior à escolha do inicial (party vazia).
- **Porta em uso:** Certifique-se de que nenhum processo anterior do programa permaneceu aberto na porta 27015.

---

## English

Automated shiny hunting tool for Pokémon Fire Red (US) v1.0 using concurrent mGBA instances coordinated via TCP sockets.

### Features

- **RNG Anti-Determinism:** Dynamic frame delays and unique seeds per instance prevent PID repetition across resets and windows.
- **Faster Cycles:** Average cycle reduced to ~20 seconds per attempt (~1,750 attempts/hour across 10 instances at 60 FPS).
- **Safe State Detection:** Identifies the winning instance by inspecting `.ss1` file modification timestamp, preventing accidental closure of the shiny window.
- **Any Starter Supported:** Works with Bulbasaur, Charmander, or Squirtle (just save in front of the desired Pokéball).

### Prerequisites

| Item | Specification |
|---|---|
| OS | Windows 10/11 (64-bit) |
| Emulator | mGBA v0.10+ installed |
| ROM | Pokémon Fire Red (US) v1.0 |
| Save | `.sav` file positioned in front of the desired starter Pokéball |
| Python | 3.10+ |

### Usage Guide

#### 1. Save Preparation
Position your character in Professor Oak's lab directly in front of the starter Pokéball of your choice, facing it and ready to interact by pressing `A`. Save through the in-game menu and close the emulator.

#### 2. Running

```powershell
# Graphical Interface (GUI)
python shiny_hunter.py

# Command Line Interface (CLI)
python shiny_hunter.py --cli
```

#### 3. Configuration
In the GUI:
1. Set the path to `mGBA.exe`.
2. Set the paths to your ROM (`.gba`) and Save (`.sav`).
3. Choose the instance count (default: 10).
4. Click **Iniciar Caçada** (Start Hunt).

#### 4. Load Lua Script
In each open mGBA window:
1. Go to **Tools** > **Scripting...**
2. Click **File** > **Load script...**
3. Select `shiny_hunt.lua`.

*Tip: mGBA's Fast-Forward feature can be toggled to speed up emulation.*

#### 5. When a Shiny is Found
1. The winning window saves a state to **Slot 1** (`.ss1`).
2. All other instances receive a stop signal and are terminated.
3. Only the shiny window remains open, showing PID and OTID on screen.

### Performance Estimates

| Mode | Time per Attempt | Throughput (10 instances) | Expected Time (1/8192) |
|---|:---:|:---:|:---:|
| Normal (60 FPS) | ~20.5 s | ~1,750 att./h | ~4.7 hours |
| Fast-Forward (4x) | ~5.0 s | ~7,000 att./h | ~1.2 hours |

### Technical Specs (Fire Red US v1.0)

- **Personality Value (PV/PID):** `0x02024284` (u32)
- **Trainer ID / Secret ID (OTID):** `0x02024288` (u32)

Shiny Formula (Gen 3):
```text
TID = OTID & 0xFFFF
SID = (OTID >> 16) & 0xFFFF
P1  = (PV >> 16) & 0xFFFF
P2  = PV & 0xFFFF

Shiny if: (P1 XOR P2 XOR TID XOR SID) < 8
```

### Troubleshooting

- **Lua script in standalone mode:** Start the Python server before loading the script inside mGBA.
- **Initial non-zero PV warning:** The save file already has a Pokémon in the party. Use a save before picking the starter.
- **Port in use:** Ensure previous instances using port 27015 are fully closed in Task Manager.
