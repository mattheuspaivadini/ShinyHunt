# Hunter Shiny

Automação para caça de Pokémon Shiny em Pokémon Fire Red (US) v1.0 utilizando instâncias simultâneas do mGBA coordenadas via socket TCP.

---

## Recursos Recentes

- **Anti-determinismo de RNG:** Variação de frames e sementes independentes por instância para evitar repetição de PIDs entre resets e janelas.
- **Ciclos mais rápidos:** Tempo médio reduzido para ~20 segundos por tentativa (~1.750 tentativas/hora com 10 instâncias a 60 FPS).
- **Detecção de Save State:** Identificação da instância vencedora por data de modificação do arquivo `.ss1`, evitando fechamento indevido da janela do shiny.
- **Executável compilado:** Versão pronta para execução em `dist/ShinyHunter.exe`.

---

## Pré-requisitos

| Item | Especificação |
|---|---|
| Sistema | Windows 10/11 (64-bit) |
| Emulador | mGBA v0.10+ instalado |
| ROM | Pokémon Fire Red (US) v1.0 |
| Save | Arquivo `.sav` salvo em frente à Pokébola do Charmander |
| Python (Opcional) | 3.10+ (apenas para executar via código-fonte) |

---

## Como Usar

### 1. Preparação do Save
Posicione o personagem em frente à Pokébola do Charmander no laboratório do Professor Carvalho, virado para ela e pronto para interagir. Salve o jogo pelo menu e feche o emulador.

### 2. Inicialização

**Opção 1 - Executável (dist):**
Execute o arquivo:
```text
dist\ShinyHunter.exe
```

**Opção 2 - Código-fonte (Python):**
```powershell
# Interface Gráfica
python shiny_hunter.py

# Linha de Comando (CLI)
python shiny_hunter.py --cli
```

### 3. Configuração
Na interface gráfica:
1. Defina o caminho do executável do mGBA.
2. Defina os caminhos da ROM (`.gba`) e do Save (`.sav`).
3. Ajuste a quantidade de instâncias desejada (padrão: 10).
4. Clique em **Iniciar Caçada**.

### 4. Carregar o Script Lua
Em cada janela aberta do mGBA:
1. Acesse **Tools** > **Scripting...**
2. Clique em **File** > **Load script...**
3. Selecione o arquivo `shiny_hunt.lua`.

*Dica: o Fast-Forward do mGBA pode ser usado para acelerar a velocidade da emulação.*

### 5. Finalização
Quando um shiny for detectado:
1. A janela que encontrou o shiny salvará o estado no **Slot 1** (`.ss1`).
2. As demais instâncias receberão comando de parada e serão fechadas.
3. A janela com o shiny permanecerá aberta com os dados (PID e OTID) exibidos na tela.

---

## Rendimento Estimado

| Modo | Tempo por Tentativa | Rendimento (10 instâncias) | Tempo Estimado (1/8192) |
|---|:---:|:---:|:---:|
| Normal (60 FPS) | ~20,5 s | ~1.750 tent./h | ~4,7 horas |
| Fast-Forward (4x) | ~5,0 s | ~7.000 tent./h | ~1,2 horas |

---

## Compilação (PyInstaller)

Para recompilar o executável na pasta `dist`:

```powershell
python -m PyInstaller --clean --onefile --windowed --name ShinyHunter --add-data "shiny_hunt.lua;." shiny_hunter.py
Copy-Item "shiny_hunt.lua", "config.json" -Destination "dist\" -Force
```

---

## Estrutura do Projeto

```text
ShinyHunt/
├── dist/
│   ├── ShinyHunter.exe
│   ├── shiny_hunt.lua
│   └── config.json
├── shiny_core.py
├── shiny_hunter.py
├── shiny_hunter_gui.py
├── shiny_hunt.lua
├── config.json
└── README.md
```

---

## Especificações Técnicas (Fire Red US v1.0)

### Endereços de Memória
- **Personality Value (PV/PID):** `0x02024284` (u32)
- **Trainer ID / Secret ID (OTID):** `0x02024288` (u32)

### Verificação de Shiny (Gen 3)
```text
TID = OTID & 0xFFFF
SID = (OTID >> 16) & 0xFFFF
P1  = (PV >> 16) & 0xFFFF
P2  = PV & 0xFFFF

Shiny se: (P1 XOR P2 XOR TID XOR SID) < 8
```

---

## Solução de Problemas

- **Script Lua em modo standalone:** Inicie o servidor Python antes de carregar o script no mGBA.
- **Aviso de PV inicial não-zero:** O save utilizado já contém um Pokémon na equipe. Use um save anterior à escolha do inicial.
- **Porta em uso:** Certifique-se de que nenhum processo anterior do programa permaneceu aberto na porta 27015.
