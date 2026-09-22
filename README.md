# ★ Shiny Charmander Hunter

Programa automatizado para encontrar um **Charmander Shiny** em **Pokémon Fire Red (US) v1.0** usando **10 instâncias simultâneas** de mGBA.

## Pré-requisitos

| Requisito | Detalhes |
|-----------|----------|
| **Sistema** | Windows 10/11 |
| **mGBA** | v0.10+ instalado em `C:\Program Files\mGBA\mGBA.exe` |
| **ROM** | Pokémon Fire Red (US) v1.0 em `C:\roms\FireRed.gba` |
| **Save** | Save posicionado em frente ao Charmander em `C:\roms\FireRed.sav` |
| **Python** | 3.10+ (não precisa de pip ou pacotes extras) |

## Como Usar

### 1. Preparar o Save

Antes de usar o programa, você precisa de um save posicionado no **laboratório do Prof. Oak**, em frente à **Poké Ball do Charmander**. O jogador deve estar de frente para a Poké Ball, pronto para pressionar A e interagir.

### 2. Executar o Programa

Você pode executar a aplicação com **Interface Gráfica (GUI)** ou em **Modo Terminal (CLI)**:

#### 🖥️ Modo Interface Gráfica (Recomendado):
Você pode simplesmente dar um **duplo clique** em `ShinyHunter.exe` na pasta do projeto, ou executar via terminal:
```powershell
cd C:\Users\Matheus\Documents\ShinyHunt
.\ShinyHunter.exe
```
*(ou `python shiny_hunter.py`)*


Na interface você poderá:
- ⏱️ Acompanhar o **tempo decorrido** em tempo real.
- 🎮 Ver a quantidade de **instâncias abertas/conectadas**.
- ⚙️ **Modificar a quantidade de instâncias** (ex: 1 a 30) diretamente na interface antes de iniciar.
- 📁 **Mudar o caminho do emulador mGBA, da ROM (.gba) e do Save (.sav)** através de botões "Procurar..." interativos.
- 📋 Copiar o caminho do script Lua com um clique.
- 📊 Ver a tabela de status de cada instância e o console de logs em tempo real.
- 🌟 Notificação de celebração instantânea ao encontrar o Shiny com dados de PV e OT ID.

#### 💻 Modo Terminal (CLI clássico):
```powershell
python shiny_hunter.py --cli
```

### 3. Carregar o Script Lua

Para **CADA** janela do mGBA aberta:

1. Menu **Tools** → **Scripting...**
2. Na janela de scripting: **File** → **Load script...**
3. Selecione o arquivo `shiny_hunt.lua` (no GUI, clique em *"Copiar Caminho do Script Lua"* para colar diretamente!)

> ⚠️ **IMPORTANTE:** Carregue o script em **todas as janelas**!

### 4. Aguardar

O programa faz tudo automaticamente:

1. 🎮 Navega pela title screen e carrega o save
2. 🔴 Interage com a Poké Ball e aceita o Charmander
3. 🔍 Verifica se é shiny (leitura direta da memória RAM)
4. ❌ Se não for shiny → soft reset e tenta novamente
5. ★ Se for shiny → salva o save state e encerra as outras instâncias

## Estatísticas

| Dado | Valor |
|------|-------|
| Chance de shiny (Gen 3) | **1 em 8192** (~0.012%) |
| Instâncias simultâneas | **Configurável (padrão 10)** |
| Tempo por tentativa | **~30 segundos** |
| Tentativas por hora (total) | **~1200** (com 10 instâncias) |
| Tempo médio esperado | **~7 horas** |

> 💡 A probabilidade é independente por tentativa. Pode demorar mais ou menos!

## Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `shiny_hunter_gui.py` | Interface Gráfica completa (Tkinter) com monitoramento |
| `shiny_hunter.py` | Ponto de entrada (inicia o GUI por padrão ou CLI com `--cli`) |
| `shiny_core.py` | Lógica central: configurações, servidor TCP e instâncias |
| `shiny_hunt.lua` | Script Lua — automação dentro do mGBA |
| `config.json` | Configurações persistentes (caminhos, portas, instâncias) |
| `README.md` | Documentação do projeto |

## Como Funciona

### Arquitetura

```
┌──────────────┐     TCP/Socket     ┌─────────────────────┐
│  Python      │◄──────────────────►│  mGBA + Lua (×10)   │
│  Manager     │    porta 27015     │  shiny_hunt.lua      │
│              │                    │                     │
│  - Lança     │  HELLO, ATTEMPT,  │  - State machine    │
│    10 mGBAs  │  RESET, SHINY     │  - Lê memória RAM   │
│  - Coordena  │◄──────────────────│  - Mash A automático│
│  - Mata proc │  STOP, ID         │  - Verifica shiny   │
│  - Display   │──────────────────►│  - Save state       │
└──────────────┘                    └─────────────────────┘
```

### Endereços de Memória (Fire Red US v1.0)

| Endereço | Dado | Tipo |
|----------|------|------|
| `0x02024284` | Personality Value (PV) do 1º Pokémon | u32 |
| `0x02024288` | OT ID (TID + SID) do 1º Pokémon | u32 |

### Fórmula Shiny (Gen 3)

```
TID = OTID & 0xFFFF          (16 bits baixos)
SID = (OTID >> 16) & 0xFFFF  (16 bits altos)
P1  = (PV >> 16) & 0xFFFF    (16 bits altos do PV)
P2  = PV & 0xFFFF            (16 bits baixos do PV)

SHINY = (P1 XOR P2 XOR TID XOR SID) < 8
```

## Solução de Problemas

### O script Lua não conecta ao servidor
- Execute `shiny_hunter.py` **ANTES** de carregar o script Lua
- O script funciona em **modo standalone** mesmo sem conexão
- Verifique se nenhum outro programa usa a porta 27015

### O mGBA trava ao carregar o script
- Verifique se a versão do mGBA é **0.10 ou superior**
- Reinicie o mGBA e tente novamente
- O `socket.connect()` pode demorar se o servidor não estiver rodando

### Os botões não estão sendo pressionados corretamente
- Os timings são calibrados para o fluxo normal do Fire Red
- Se necessário, ajuste os valores no início de `shiny_hunt.lua`:
  - `WAIT_AFTER_RESET`: tempo após reset antes de pressionar
  - `TITLE_MASH_DURATION`: tempo na title screen
  - `PRESS_INTERVAL`: velocidade de pressionar A

### Endereços de memória incorretos
- Este programa é feito para **Fire Red (US) v1.0** (Game Code: BPRE Rev 0)
- Se sua ROM for outra versão ou idioma, os endereços precisam ser ajustados
- Verifique o console do mGBA para mensagens de erro

### O programa encontra "PV inicial não-zero"
- Significa que o save já tem um Pokémon na party
- O save deve estar no ponto **antes** de pegar o Charmander
- Crie um novo save posicionado em frente à Poké Ball do Charmander
