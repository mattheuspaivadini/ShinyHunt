-- ============================================================
-- Hunter Shiny v1.0 — Iniciais de Hoenn (Treecko / Torchic / Mudkip)
-- Pokemon Emerald (US) v1.0 (BPEE) — mGBA Automation Script
-- ============================================================
-- COMO USAR:
--   1. No jogo, posicione seu personagem em frente a bolsa do
--      Prof. Birch na Rota 101 (quando ele esta sendo atacado).
--   2. Certifique-se de estar com a party vazia (0 Pokemon).
--   3. Salve o jogo pelo menu (Start > Save) exatamente nessa posicao.
--   4. Execute o ShinyHunter (Interface Grafica ou CLI) e selecione
--      Pokemon Emerald e o inicial desejado.
--   5. No mGBA: Tools > Scripting > File > Load script.
--   6. Selecione este arquivo (iniciais_emerald.lua).
-- ============================================================

-- ============================================================
-- MODO DE TESTE / DEBUG RAPIDO:
-- Para testar a navegacao na bolsa, deteccao de shiny e salvamento
-- sem esperar a probabilidade real (1/8192), mude para true:
local DEBUG_FORCE_SHINY = false          -- true = forca deteccao de shiny para teste
local DEBUG_FORCE_SHINY_ATTEMPT = 2      -- tentativa em que o shiny sera simulado
-- ============================================================

-- ==================== CONFIGURACAO DO INICIAL ====================

-- ID pre-definido caso este script tenha sido gerado para uma instancia especifica
local SCRIPT_INSTANCE_ID = SCRIPT_INSTANCE_ID or nil

-- Inicial desejado para caçar:
--   "treecko"  = Planta (Move o cursor para a Esquerda ◀)
--   "torchic"  = Fogo   (Mantem o cursor no Centro ●)
--   "mudkip"   = Agua   (Move o cursor para a Direita ▶)
local TARGET_STARTER = TARGET_STARTER or "mudkip"

-- Servidor Python (para coordenacao entre instancias)
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 27015

-- Enderecos de memoria - Pokemon Emerald (US) v1.0 (BPEE Rev 0) - SOMENTE LEITURA (READ-ONLY)
-- AVISO: NENHUMA escrita de memoria e feita para nao corromper o checksum do Pokemon (evita Bad Egg)
local ADDR_PARTY_PV               = 0x020244EC  -- Personality Value do 1o Pokemon (gPlayerParty[0].personality)
local ADDR_PARTY_OTID             = 0x020244F0  -- OT ID do 1o Pokemon
local ADDR_MAIN_CALLBACK2         = 0x030022C4  -- Ponteiro do loop principal do jogo (gMain.callback2)
local ADDR_TASK0_FUNC             = 0x03005E00  -- Ponteiro da funcao ativa da Task 0 (gTasks[0].func)
local ADDR_TASK0_STARTER          = 0x03005E08  -- Indice da selecao na bolsa (gTasks[0].data[0]: 0=Treecko, 1=Torchic, 2=Mudkip)

-- Callbacks conhecidos do Pokemon Emerald US (BPEE)
local FN_CB2_MAIN_MENU            = 0x081BFAB4  -- Loop do Menu Principal (CB2_MainMenu)
local FN_CB2_MAIN_MENU_INIT       = 0x081BFDB0  -- Init do Menu Principal (CB2_InitMainMenu)
local FN_CB2_OVERWORLD            = 0x08038420  -- Loop do Overworld (CB2_Overworld)
local FN_CB2_STARTER_CHOOSE       = 0x081341E0  -- Callback da tela da bolsa (CB2_StarterChoose)
local FN_TASK_STARTER_INPUT       = 0x0813425C  -- Funcao que processa as teclas na bolsa (Task_HandleStarterChooseInput)

-- Constantes de teclas do GBA (C.GBA_KEY)
local KEY_A      = 0
local KEY_B      = 1
local KEY_SELECT = 2
local KEY_START  = 3
local KEY_RIGHT  = 4
local KEY_LEFT   = 5
local KEY_UP     = 6
local KEY_DOWN   = 7
local KEY_R      = 8
local KEY_L      = 9

-- Timings (em frames, 60 fps)
local WAIT_AFTER_RESET    = 240   -- ~4.0s: espera BIOS + intro Game Freak
local MASH_TIMEOUT        = 1800  -- ~30s: timeout de seguranca

-- Atraso extra maximo (em frames) sorteado a cada tentativa (garante variacao de RNG)
local TITLE_EXTRA_MAX     = 180   -- ate 3s a mais na title screen
local LOADING_EXTRA_MAX   = 120   -- ate 2s a mais apos carregar save

-- ==================== ESTADOS ====================

local STATE = {
    INIT            = "INIT",
    TITLE_WAIT      = "TITLE_WAIT",
    TITLE_PRESS     = "TITLE_PRESS",
    MAIN_MENU       = "MAIN_MENU",
    LOADING         = "LOADING",
    OPEN_BAG        = "OPEN_BAG",
    SELECT_STARTER  = "SELECT_STARTER",
    OPEN_POKEBALL   = "OPEN_POKEBALL",
    CONFIRM_CHOICE  = "CONFIRM_CHOICE",
    CHECK_SHINY     = "CHECK_SHINY",
    SHINY_FOUND     = "SHINY_FOUND",
    RESETTING       = "RESETTING",
    DONE            = "DONE"
}

-- ==================== NORMALIZAÇÃO DO ALVO ====================

local function getNormalizedStarter(starterStr)
    local s = starterStr

    if not s or s == "" then
        s = TARGET_STARTER
    end

    if os and type(os.getenv) == "function" then
        local ok, envVal = pcall(function() return os.getenv("SHINY_EMERALD_STARTER") end)
        if ok and envVal and envVal ~= "" then
            s = envVal
        end
    end

    if io and type(io.open) == "function" then
        local candidates = {
            "emerald_starter.txt",
            "../emerald_starter.txt",
            "instances/emerald_starter.txt",
            "C:/roms/FireRed/emerald_starter.txt",
            "C:/roms/emerald_starter.txt"
        }
        for _, path in ipairs(candidates) do
            local ok, f = pcall(function() return io.open(path, "r") end)
            if ok and f then
                local content = f:read("*all")
                f:close()
                if content and content ~= "" then
                    local trimmed = content:gsub("%s+", ""):lower()
                    if trimmed == "treecko" or trimmed == "torchic" or trimmed == "mudkip" then
                        s = trimmed
                        break
                    end
                end
            end
        end
    end

    local clean = string.lower(tostring(s or "mudkip")):gsub("%s+", "")
    if clean:find("tree") or clean:find("planta") or clean:find("grass") then
        return "treecko", "Treecko (Planta - Seta Esquerda ◀)", 0, 277
    elseif clean:find("mud") or clean:find("agua") or clean:find("water") then
        return "mudkip", "Mudkip (Agua - Seta Direita ▶)", 2, 283
    else
        return "torchic", "Torchic (Fogo - Centro ●)", 1, 280
    end
end

local normalizedStarter, starterDisplayName, targetIdx, targetSpeciesId = getNormalizedStarter(TARGET_STARTER)

-- ==================== VARIÁVEIS GLOBAIS ====================

local currentState        = STATE.INIT
local stateFrames         = 0         -- Frames no estado atual
local totalFrames         = 0         -- Frames totais desde o inicio
local attempts            = 0         -- Numero de tentativas
local initialPV           = 0         -- PV detectado ao carregar o save
local sock                = nil       -- Socket TCP para o servidor Python
local connected           = false     -- Se esta conectado ao servidor
local instanceId          = "?"       -- ID da instancia (atribuido pelo servidor)
local shouldStop          = false     -- Se deve parar (shiny encontrado em outra instancia)
local lastStateName       = ""        -- Para log de mudanca de estado
local titleExtra          = 0         -- sorteado no INIT
local loadingExtra        = 0         -- sorteado no INIT
local targetSettledFrames = 0         -- Frames consecutivos com cursor perfeitamente estabilizado no alvo

-- ==================== FUNÇÕES UTILITÁRIAS ====================

--- Formata um numero como hexadecimal de 8 digitos
local function hex(val)
    return string.format("0x%08X", val or 0)
end

--- Detecta o numero real desta instancia atraves de multiplos metodos
local function detectInstanceId()
    if SCRIPT_INSTANCE_ID and type(SCRIPT_INSTANCE_ID) == "number" and SCRIPT_INSTANCE_ID >= 1 and SCRIPT_INSTANCE_ID <= 30 then
        return SCRIPT_INSTANCE_ID
    end

    if emu and type(emu.read8) == "function" then
        local ok, val = pcall(function() return emu:read8(0x080000B5) end)
        if ok and val and val >= 1 and val <= 30 then
            return val
        end
    end

    if os and type(os.getenv) == "function" then
        local ok, envVal = pcall(function() return os.getenv("SHINY_INSTANCE_ID") end)
        if ok and envVal then
            local num = tonumber(envVal)
            if num and num >= 1 and num <= 30 then
                return num
            end
        end
    end

    if io and type(io.open) == "function" then
        local ok, f = pcall(function() return io.open("instance_id.txt", "r") end)
        if ok and f then
            local content = f:read("*all")
            f:close()
            local num = tonumber(content and content:match("%d+"))
            if num and num >= 1 and num <= 30 then
                return num
            end
        end
    end

    return nil
end

--- Muda o estado da maquina de estados
local function changeState(newState)
    currentState = newState
    stateFrames = 0
    targetSettledFrames = 0
    if newState ~= lastStateName then
        lastStateName = newState
    end
end

--- Pressiona uma tecla do GBA via controle nativo do emulador
local function pressKey(key)
    pcall(function()
        emu:addKey(key)
        emu:setKeys(1 << key)
    end)
end

--- Pressiona multiplas teclas do GBA via bitmask
local function pressKeys(mask)
    pcall(function()
        emu:setKeys(mask)
    end)
end

--- Solta todas as teclas do GBA
local function releaseAll()
    pcall(function()
        emu:setKeys(0)
        emu:clearKeys(0x3FF)
    end)
end

--- Grava log persistente em arquivo
local function logToFile(msg)
    pcall(function()
        local f = io.open("shiny_emerald.log", "a")
        if f then
            f:write(string.format("[%s] %s\n", os.date("%H:%M:%S"), msg))
            f:close()
        end
    end)
end

--- Le o Personality Value do primeiro Pokemon da party (SOMENTE LEITURA)
local function readPV()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_PV) end)
    if ok and val then return val end
    return 0
end

--- Le o OT ID do primeiro Pokemon da party (SOMENTE LEITURA)
local function readOTID()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_OTID) end)
    if ok and val then return val end
    return 0
end

--- Verifica se um Pokemon e shiny baseado no PV e OTID
--- Formula Gen 3: (PV_high XOR PV_low XOR TID XOR SID) < 8
local function isShiny(pv, otid)
    if pv == 0 then return false end
    local tid = otid & 0xFFFF
    local sid = (otid >> 16) & 0xFFFF
    local p1 = (pv >> 16) & 0xFFFF
    local p2 = pv & 0xFFFF
    local xorVal = p1 ~ p2 ~ tid ~ sid
    return xorVal < 8
end

--- Verifica se o Menu Principal (Continue / New Game) esta ativo na memoria
local function isMainMenuOpen()
    local ok, cb2 = pcall(function() return emu:read32(ADDR_MAIN_CALLBACK2) end)
    if ok and cb2 then
        local c = cb2 & ~1
        if c == FN_CB2_MAIN_MENU or c == FN_CB2_MAIN_MENU_INIT then
            return true
        end
    end
    return false
end

--- Verifica se o jogador esta no Overworld andando no mapa
local function isOverworldOpen()
    local ok, cb2 = pcall(function() return emu:read32(ADDR_MAIN_CALLBACK2) end)
    if ok and cb2 then
        local c = cb2 & ~1
        if c == FN_CB2_OVERWORLD or c == 0x080565B4 or c == 0x08059820 then
            return true
        end
    end
    return false
end

--- Verifica se a tela da bolsa do Prof. Birch abriu na memoria (SOMENTE LEITURA)
local function isStarterBagOpen()
    local ok, cb2 = pcall(function() return emu:read32(ADDR_MAIN_CALLBACK2) end)
    if ok and cb2 then
        local c = cb2 & ~1
        if c == FN_CB2_STARTER_CHOOSE or c == 0x081341A0 then
            return true
        end
    end
    return false
end

--- Verifica se a task de escolha de inicial está ativa aguardando input (SOMENTE LEITURA)
local function isStarterInputReady()
    if not isStarterBagOpen() then return false end
    local ok, func = pcall(function() return emu:read32(ADDR_TASK0_FUNC) end)
    if ok and func and (func & ~1) == FN_TASK_STARTER_INPUT then
        return true
    end

    -- Varredura alternativa caso a task de escolha esteja em outro índice (gTasks[0..15])
    local G_TASKS_BASE = 0x03005E00
    for t = 0, 15 do
        local taskAddr = G_TASKS_BASE + (t * 40)
        local okF, fVal = pcall(function() return emu:read32(taskAddr) end)
        if okF and fVal and (fVal & ~1) == FN_TASK_STARTER_INPUT then
            return true
        end
    end

    return false
end

--- Le o indice atual da selecao na tela de iniciais (SOMENTE LEITURA)
--- 0 = Treecko, 1 = Torchic, 2 = Mudkip
local function getStarterSelection()
    -- 1. Verifica Task 0 diretamente
    local ok, sel = pcall(function() return emu:read16(ADDR_TASK0_STARTER) end)
    if ok and sel and sel >= 0 and sel <= 2 then
        local okF, func = pcall(function() return emu:read32(ADDR_TASK0_FUNC) end)
        if okF and func then
            local cleanFunc = func & ~1
            if cleanFunc == FN_TASK_STARTER_INPUT or cleanFunc == 0x0813423C or cleanFunc == 0x08134641 or cleanFunc == 0x08134775 or cleanFunc == 0x08134341 then
                return sel
            end
        end
    end

    -- 2. Varredura em todas as 16 tasks (gTasks[0..15])
    local G_TASKS_BASE = 0x03005E00
    for t = 0, 15 do
        local taskAddr = G_TASKS_BASE + (t * 40)
        local okF, func = pcall(function() return emu:read32(taskAddr) end)
        if okF and func then
            local cleanFunc = func & ~1
            if cleanFunc == FN_TASK_STARTER_INPUT or cleanFunc == 0x08134641 or cleanFunc == 0x08134775 then
                local okS, val = pcall(function() return emu:read16(taskAddr + 8) end)
                if okS and val and val >= 0 and val <= 2 then
                    return val
                end
            end
        end
    end

    if ok and sel and sel >= 0 and sel <= 2 then
        return sel
    end

    return -1
end

-- Tabela de decodificação de espécie do Pokémon (GBA Gen 3)
local GROWTH_BLOCK = {
    [0]=0, [1]=0, [2]=0, [3]=0, [4]=0, [5]=0,
    [6]=1, [7]=1, [8]=2, [9]=3, [10]=2, [11]=3,
    [12]=1, [13]=1, [14]=2, [15]=3, [16]=2, [17]=3,
    [18]=1, [19]=1, [20]=2, [21]=3, [22]=2, [23]=3
}

--- Lê a espécie do primeiro Pokémon da party a partir dos dados descriptografados
local function readSpecies()
    local pv = readPV()
    local otid = readOTID()
    if pv == 0 then return 0 end
    local ok, species = pcall(function()
        local key = pv ~ otid
        local order = pv % 24
        local block = GROWTH_BLOCK[order] or 0
        local growthAddr = (ADDR_PARTY_PV + 32) + (block * 12)
        local rawWord = emu:read16(growthAddr)
        return rawWord ~ (key & 0xFFFF)
    end)
    if ok and species then
        return species
    end
    return 0
end

-- ==================== FUNÇÕES DE SOCKET ====================

--- Tenta conectar ao servidor Python
local function connectToServer()
    if not socket then
        connected = false
        return
    end

    local ok, result = pcall(function()
        return socket.connect(SERVER_HOST, SERVER_PORT)
    end)

    if ok and result then
        sock = result
        connected = true
        console:log("[Socket] Conectado ao servidor na porta " .. SERVER_PORT)
    else
        sock = nil
        connected = false
    end
end

--- Envia uma mensagem para o servidor Python
local function sendMessage(msg)
    if not connected or not sock then return end
    local ok, err = pcall(function()
        sock:send(msg .. "\n")
    end)
    if not ok then
        connected = false
    end
end

--- Verifica mensagens do servidor (non-blocking)
local function checkServerMessages()
    if not connected or not sock then return end

    local ok, result = pcall(function()
        return sock:receive(256)
    end)

    if not ok or not result or type(result) ~= "string" or #result == 0 then return end

    local data = result

    if string.find(data, "STOP") then
        shouldStop = true
        console:log("")
        console:log("!!! SHINY encontrado em OUTRA instancia !!!")
        console:log("!!! Parando esta instancia...           !!!")
        console:log("")
        changeState(STATE.DONE)
    end
    if string.find(data, "ID|") then
        local id = string.match(data, "ID|(%d+)")
        if id then
            instanceId = id
            console:log("[Info] ID da instancia confirmado pelo servidor: #" .. instanceId)
            pcall(function()
                local numId = tonumber(instanceId) or 1
                math.randomseed(os.time() + math.floor(os.clock() * 1000000) + numId * 7919)
                math.random(); math.random(); math.random()
            end)
        end
    end
end

-- ==================== CALLBACK DE FRAME ====================

local function onFrame()
    totalFrames = totalFrames + 1
    stateFrames = stateFrames + 1

    -- Sincronização periódica com servidor Python
    if connected and totalFrames % 60 == 0 then
        checkServerMessages()
    end

    -- Identificação dinâmica de instância
    if (instanceId == "?" or instanceId == nil) and totalFrames % 30 == 0 then
        local detected = detectInstanceId()
        if detected then
            instanceId = tostring(detected)
            console:log("[Info] Instancia identificada dinamicamente: #" .. instanceId)
            pcall(function()
                math.randomseed(os.time() + math.floor(os.clock() * 1000000) + detected * 7919)
                math.random(); math.random(); math.random()
            end)
            if connected then
                sendMessage("IDENTIFY|" .. detected)
            end
        end
    end

    if shouldStop then
        releaseAll()
        return
    end

    -- ========== MÁQUINA DE ESTADOS (100% GAMEPAD INPUT) ==========

    if currentState == STATE.INIT then
        if attempts == 0 then
            pcall(function() emu:reset() end)
        end
        attempts = attempts + 1
        local instOffset = tonumber(instanceId) or 1

        -- Re-detecta o alvo dinamicamente para garantir sincronia com a interface
        normalizedStarter, starterDisplayName, targetIdx, targetSpeciesId = getNormalizedStarter(TARGET_STARTER)

        titleExtra   = (math.random(0, TITLE_EXTRA_MAX) + instOffset * 7) % (TITLE_EXTRA_MAX + 1)
        loadingExtra = (math.random(0, LOADING_EXTRA_MAX) + instOffset * 13) % (LOADING_EXTRA_MAX + 1)
        initialPV = 0
        releaseAll()

        console:log("========================================")
        console:log("  Tentativa #" .. attempts .. "  (Instancia #" .. instanceId .. ")")
        console:log("  Alvo: " .. starterDisplayName)
        console:log("  Delays: title +" .. titleExtra .. " | loading +" .. loadingExtra)
        console:log("========================================")

        sendMessage("ATTEMPT|" .. attempts)
        changeState(STATE.TITLE_WAIT)

    elseif currentState == STATE.TITLE_WAIT then
        releaseAll()

        -- Se por acaso ja estiver no Menu Principal, Overworld ou Bolsa:
        if isStarterBagOpen() then
            console:log("[State] Bolsa detectada precocemente! Indo para selecao...")
            changeState(STATE.SELECT_STARTER)
            return
        elseif isOverworldOpen() then
            console:log("[State] Overworld detectado precocemente! Indo para interacao com a bolsa...")
            changeState(STATE.OPEN_BAG)
            return
        elseif isMainMenuOpen() then
            console:log("[State] Menu Principal detectado! Indo para selecao de Continue...")
            changeState(STATE.MAIN_MENU)
            return
        end

        -- Espera intro inicial (~240 frames = 4s) + delay de RNG
        if stateFrames >= WAIT_AFTER_RESET + titleExtra then
            console:log("[State] Tela de titulo (Rayquaza) - aguardando/pressionando Start...")
            changeState(STATE.TITLE_PRESS)
        end

    elseif currentState == STATE.TITLE_PRESS then
        -- Se ja detectou Menu Principal, Overworld ou Bolsa:
        if isStarterBagOpen() then
            releaseAll()
            console:log("[State] Bolsa detectada! Indo para a selecao do inicial...")
            changeState(STATE.SELECT_STARTER)
            return
        elseif isOverworldOpen() then
            releaseAll()
            console:log("[State] Overworld detectado! Indo para a interacao com a bolsa...")
            changeState(STATE.OPEN_BAG)
            return
        elseif isMainMenuOpen() then
            releaseAll()
            console:log("[State] Menu Principal carregado! Selecionando Continue...")
            changeState(STATE.MAIN_MENU)
            return
        end

        -- Pressiona START de forma cadenciada a cada 30 frames (4 frames segurando, 26 solto)
        -- para avancar da tela de titulo SEM spamar botoes
        local cycle = stateFrames % 30
        if cycle == 0 then
            pressKey(KEY_START)
        elseif cycle == 4 then
            releaseAll()
        end

        -- Timeout de seguranca: apos 180 frames (~3s), avanca para o MAIN_MENU
        if stateFrames >= 180 then
            releaseAll()
            console:log("[State] Avancando para o Menu Principal...")
            changeState(STATE.MAIN_MENU)
        end

    elseif currentState == STATE.MAIN_MENU then
        if isStarterBagOpen() then
            releaseAll()
            console:log("[State] Bolsa detectada! Indo para a selecao do inicial...")
            changeState(STATE.SELECT_STARTER)
            return
        elseif isOverworldOpen() then
            releaseAll()
            console:log("[State] Overworld detectado! Indo para a interacao com a bolsa...")
            changeState(STATE.OPEN_BAG)
            return
        end

        -- Aguarda 25 frames com as teclas soltas para garantir fade-in do menu e debounce livre
        if stateFrames < 25 then
            releaseAll()
            return
        end

        -- No Menu Principal, o cursor comeca em "CONTINUE" por padrao quando ha save.
        -- Dá UM UNICO toque firme em 'A' (frames 25 a 30) e NUNCA fica repetindo!
        if stateFrames >= 25 and stateFrames <= 30 then
            if stateFrames == 25 then
                console:log("[State] Selecionando 'Continue' no Menu Principal (toque unico)...")
            end
            pressKey(KEY_A)
        else
            releaseAll()
        end

        -- Apos confirmar 'Continue', avanca para LOADING apos frame 50
        if stateFrames >= 50 then
            releaseAll()
            console:log("[State] Aguardando carregamento do save no Overworld...")
            changeState(STATE.LOADING)
        end

    elseif currentState == STATE.LOADING then
        -- DURANTE O CARREGAMENTO DO SAVE, NENHUM BOTAO PODE SER PRESSIONADO!
        releaseAll()

        if isStarterBagOpen() then
            console:log("[State] Bolsa detectada! Indo para a selecao do inicial...")
            changeState(STATE.SELECT_STARTER)
            return
        end

        if isOverworldOpen() then
            -- Armazena o PV que estiver na memoria (0 no save normal)
            initialPV = readPV()
            console:log("[State] Jogo carregado no Overworld (detectado por memoria)! Interagindo com a bolsa...")
            logToFile("Jogo carregado no overworld. Interagindo com a bolsa...")
            changeState(STATE.OPEN_BAG)
            return
        end

        -- Fallback de tempo: espera ~90 frames (1.5s) + loadingExtra
        if stateFrames >= 90 + loadingExtra then
            initialPV = readPV()
            console:log("[State] Jogo carregado no Overworld (tempo)! Interagindo com a bolsa do Prof. Birch...")
            logToFile("Jogo carregado no overworld. Interagindo com a bolsa...")
            changeState(STATE.OPEN_BAG)
        end

    elseif currentState == STATE.OPEN_BAG then
        -- 1. Se a task de input da bolsa já está pronta para receber comando:
        if isStarterInputReady() then
            releaseAll()
            if stateFrames >= 25 then
                console:log("[State] Bolsa aberta e pronta para selecao! Alvo: " .. starterDisplayName)
                logToFile("Bolsa aberta e pronta para selecao: " .. starterDisplayName)
                changeState(STATE.SELECT_STARTER)
            end
            return
        end

        -- 2. Se a bolsa já abriu (callback2 da bolsa), NUNCA pressione 'A' para nao escolher Torchic!
        if isStarterBagOpen() then
            releaseAll()
            return
        end

        -- 3. No overworld em frente a bolsa, aguarda estabilizacao de 20 frames
        if stateFrames < 20 then
            releaseAll()
            return
        end

        -- Dá UM TOQUE isolado em 'A' (frames 20 a 26) para abrir a bolsa
        if stateFrames >= 20 and stateFrames <= 26 then
            pressKey(KEY_A)
        else
            releaseAll()
        end

        -- Se a bolsa ainda nao abriu apos 90 frames, da mais um unico toque de seguranca
        if stateFrames >= 90 and stateFrames <= 96 then
            pressKey(KEY_A)
        end

        -- Timeout de seguranca
        if stateFrames >= 240 then
            releaseAll()
            console:log("[State] Timeout aguardando bolsa. Avancando para selecao...")
            changeState(STATE.SELECT_STARTER)
        end

    elseif currentState == STATE.SELECT_STARTER then
        -- Pausa inicial de 25 frames com tudo solto para garantir que a animacao da bolsa terminou
        if stateFrames < 25 then
            releaseAll()
            targetSettledFrames = 0
            return
        end

        local curSel = getStarterSelection()

        -- Se o alvo for TREECKO (seta para a ESQUERDA ◀, indice 0):
        if targetIdx == 0 then
            if curSel == 0 then
                releaseAll()
                targetSettledFrames = targetSettledFrames + 1
                -- Exige 25 frames consecutivos com cursor firme no slot 0
                if targetSettledFrames >= 25 then
                    console:log("[State] Treecko selecionado e estabilizado no cursor (slot 0)! Abrindo Pokebola...")
                    logToFile("Treecko selecionado e estabilizado no cursor (slot 0)! Abrindo Pokebola...")
                    changeState(STATE.OPEN_POKEBALL)
                end
                return
            end

            targetSettledFrames = 0
            -- Envia pulso de D-Pad ESQUERDA a cada 20 frames (segura 6 frames, solta 14)
            local cycle = (stateFrames - 25) % 20
            if cycle < 6 then
                console:log("[Input] Pressionando D-Pad ESQUERDA para Treecko (slot atual=" .. tostring(curSel) .. ")...")
                pressKey(KEY_LEFT)
            else
                releaseAll()
            end

        -- Se o alvo for MUDKIP (seta para a DIREITA ▶, indice 2):
        elseif targetIdx == 2 then
            if curSel == 2 then
                releaseAll()
                targetSettledFrames = targetSettledFrames + 1
                -- Exige 25 frames consecutivos com cursor firme no slot 2
                if targetSettledFrames >= 25 then
                    console:log("[State] Mudkip selecionado e estabilizado no cursor (slot 2)! Abrindo Pokebola...")
                    logToFile("Mudkip selecionado e estabilizado no cursor (slot 2)! Abrindo Pokebola...")
                    changeState(STATE.OPEN_POKEBALL)
                end
                return
            end

            targetSettledFrames = 0
            -- Envia pulso de D-Pad DIREITA a cada 20 frames (segura 6 frames, solta 14)
            local cycle = (stateFrames - 25) % 20
            if cycle < 6 then
                console:log("[Input] Pressionando D-Pad DIREITA para Mudkip (slot atual=" .. tostring(curSel) .. ")...")
                pressKey(KEY_RIGHT)
            else
                releaseAll()
            end

        -- Se o alvo for TORCHIC (centro ●, indice 1):
        else
            if curSel == 1 or curSel == -1 then
                releaseAll()
                targetSettledFrames = targetSettledFrames + 1
                if targetSettledFrames >= 25 then
                    console:log("[State] Torchic mantido e estabilizado no centro (slot 1). Abrindo Pokebola...")
                    logToFile("Torchic mantido e estabilizado no centro (slot 1). Abrindo Pokebola...")
                    changeState(STATE.OPEN_POKEBALL)
                end
                return
            elseif curSel == 0 then
                targetSettledFrames = 0
                local cycle = (stateFrames - 25) % 20
                if cycle < 6 then pressKey(KEY_RIGHT) else releaseAll() end
            elseif curSel == 2 then
                targetSettledFrames = 0
                local cycle = (stateFrames - 25) % 20
                if cycle < 6 then pressKey(KEY_LEFT) else releaseAll() end
            end
        end

        -- Timeout de seguranca apos 300 frames (~5s)
        if stateFrames >= 300 then
            releaseAll()
            if curSel == targetIdx then
                changeState(STATE.OPEN_POKEBALL)
            else
                console:log("[AVISO] Cursor nao estabilizou no alvo (" .. tostring(curSel) .. " != " .. tostring(targetIdx) .. "). Reajustando...")
                changeState(STATE.SELECT_STARTER)
            end
        end

    elseif currentState == STATE.OPEN_POKEBALL then
        -- Trava ABSOLUTA de seguranca: se o cursor estiver fora do alvo, NUNCA aperte 'A'!
        local curSel = getStarterSelection()
        if curSel ~= -1 and curSel ~= targetIdx then
            console:log("[ALERTA CRITICO] Cursor fora do alvo (" .. tostring(curSel) .. " != " .. tostring(targetIdx) .. ")! Corrigindo selecao imediatamente...")
            logToFile("ALERTA: Cursor fora do alvo (" .. tostring(curSel) .. " != " .. tostring(targetIdx) .. "). Corrigindo...")
            releaseAll()
            changeState(STATE.SELECT_STARTER)
            return
        end

        -- Aguarda pausa de 15 frames para garantir debounce e animacao
        if stateFrames < 15 then
            releaseAll()
            return
        end

        -- Pressiona 'A' de forma firme por 6 frames (frames 15 a 21) para abrir a Pokebola
        if stateFrames >= 15 and stateFrames <= 21 then
            if stateFrames == 15 then
                console:log("[State] Abrindo Pokebola de " .. starterDisplayName .. "...")
                logToFile("Abrindo Pokebola de " .. starterDisplayName)
            end
            pressKey(KEY_A)
        else
            releaseAll()
        end

        -- Aguarda o zoom do circulo branco, o cry e a caixa YES/NO surgirem (~85 frames)
        if stateFrames >= 85 then
            releaseAll()
            console:log("[State] Confirmando 'SIM' para " .. starterDisplayName .. "...")
            logToFile("Confirmando 'SIM' para " .. starterDisplayName)
            changeState(STATE.CONFIRM_CHOICE)
        end

    elseif currentState == STATE.CONFIRM_CHOICE then
        -- Monitora o PV do slot 1: quando for gerado e diferir do inicial, o Pokemon chegou!
        local currentPV = readPV()

        if currentPV ~= 0 and currentPV ~= initialPV then
            releaseAll()
            console:log("")
            console:log("[!!!] Pokemon recebido legitimamente na party (Slot 1)!")
            console:log("[!!!] PV = " .. hex(currentPV))
            logToFile("Pokemon recebido legitimamente! PV = " .. hex(currentPV))
            changeState(STATE.CHECK_SHINY)
            return
        end

        -- Pulsa 'A' a cada 10 frames para confirmar 'YES' e passar o dialogo do Prof. Birch
        local cycle = stateFrames % 10
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == 4 then
            releaseAll()
        end

        -- Timeout de seguranca: 1800 frames (~30s)
        if stateFrames >= MASH_TIMEOUT then
            releaseAll()
            console:log("[AVISO] Timeout na confirmacao! Resetando...")
            logToFile("AVISO: Timeout na confirmacao. Resetando...")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.CHECK_SHINY then
        if stateFrames < 5 then
            releaseAll()
            return
        end

        local pv   = readPV()
        local otid = readOTID()

        if pv == 0 then
            console:log("[AVISO] PV = 0 durante check. Resetando...")
            changeState(STATE.RESETTING)
            return
        end

        local tid    = otid & 0xFFFF
        local sid    = (otid >> 16) & 0xFFFF
        local p1     = (pv >> 16) & 0xFFFF
        local p2     = pv & 0xFFFF
        local xorVal = p1 ~ p2 ~ tid ~ sid

        local speciesId = readSpecies()
        local speciesNames = {
            [277] = "Treecko",
            [280] = "Torchic",
            [283] = "Mudkip"
        }
        local actualName = speciesNames[speciesId] or ("Especie #" .. tostring(speciesId))

        console:log("  Pokemon alvo:    " .. starterDisplayName)
        console:log("  Pokemon obtido:  " .. actualName)
        console:log("  PV:              " .. hex(pv))
        console:log("  OTID:            " .. hex(otid))
        console:log("  TID:             " .. tid)
        console:log("  SID:             " .. sid)
        console:log("  XOR:             " .. xorVal .. " (shiny se < 8)")
        logToFile(string.format("Check: alvo=%s, obtido=%s, PV=%s, OTID=%s, XOR=%d", starterDisplayName, actualName, hex(pv), hex(otid), xorVal))

        -- Validação estrita de espécie
        local isCorrectSpecies = true
        if targetSpeciesId and targetSpeciesId ~= 0 and speciesId ~= 0 and speciesId ~= targetSpeciesId then
            isCorrectSpecies = false
        end

        if not isCorrectSpecies then
            console:log("  [ALERTA] Especie obtida (" .. actualName .. ") difere do alvo configurado (" .. starterDisplayName .. ")! Resetando...")
            logToFile("ALERTA: Especie obtida difere do alvo configurado. Resetando...")
            changeState(STATE.RESETTING)
            return
        end

        local shiny = isShiny(pv, otid)

        -- Simulação para modo de teste
        if DEBUG_FORCE_SHINY and attempts >= DEBUG_FORCE_SHINY_ATTEMPT then
            shiny = true
            console:log("  [DEBUG] Modo de teste ativo: forcando deteccao de Shiny!")
        end

        if shiny then
            console:log("")
            logToFile("SHINY ENCONTRADO! PV=" .. hex(pv) .. " OTID=" .. hex(otid))
            changeState(STATE.SHINY_FOUND)
        else
            console:log("  Resultado: NAO shiny")
            console:log("")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.SHINY_FOUND then
        releaseAll()

        local pv   = readPV()
        local otid = readOTID()

        console:log("*********************************************************")
        console:log("*                                                       *")
        console:log("*                 SHINY ENCONTRADO!!!                   *")
        console:log("*                                                       *")
        console:log("*********************************************************")
        console:log("")
        console:log("  Pokemon:   " .. starterDisplayName)
        console:log("  Instancia: #" .. instanceId)
        console:log("  Tentativa: #" .. attempts)
        console:log("  PV:        " .. hex(pv))
        console:log("  OTID:      " .. hex(otid))
        console:log("")

        -- Salva o save state no slot 1
        local ok, result = pcall(function()
            return emu:saveStateSlot(1)
        end)

        if ok and result ~= false then
            console:log("  Save state salvo no Slot 1!")
        else
            console:log("  [AVISO] Nao foi possivel salvar o state no slot 1 diretamente")
            pcall(function()
                emu:saveStateFile("shiny_emerald_" .. normalizedStarter .. ".ss1")
                console:log("  Save state salvo como 'shiny_emerald_" .. normalizedStarter .. ".ss1'")
            end)
        end

        console:log("")
        console:log("  Voce pode carregar o save state (Slot 1) e continuar jogando!")
        console:log("")

        sendMessage("SHINY|" .. hex(pv) .. "|" .. hex(otid) .. "|" .. attempts)
        changeState(STATE.DONE)

    elseif currentState == STATE.RESETTING then
        releaseAll()
        if stateFrames >= 25 then
            sendMessage("RESET|" .. attempts)
            pcall(function() emu:reset() end)
            changeState(STATE.INIT)
        end

    elseif currentState == STATE.DONE then
        releaseAll()
    end
end

-- ==================== INICIALIZAÇÃO ====================

console:log("")
console:log("=========================================================")
console:log("  Hunter Shiny v1.0 — Iniciais de Hoenn")
console:log("  Pokemon Emerald (US) v1.0 (BPEE)")
console:log("  Alvo configurado: " .. starterDisplayName)
console:log("=========================================================")
console:log("")
console:log("  Enderecos de memoria (Emerald US):")
console:log("    Party Slot 1 PV:   " .. hex(ADDR_PARTY_PV))
console:log("    Party Slot 1 OTID: " .. hex(ADDR_PARTY_OTID))
console:log("")

local detected = detectInstanceId()
if detected then
    instanceId = tostring(detected)
    console:log("[Info] Instancia identificada localmente: #" .. instanceId)
    pcall(function()
        math.randomseed(os.time() + math.floor(os.clock() * 1000000) + detected * 7919)
        math.random(); math.random(); math.random()
    end)
else
    pcall(function()
        math.randomseed(os.time() + math.floor(os.clock() * 1000000))
    end)
end

connectToServer()
if connected then
    if detected then
        sendMessage("HELLO|" .. detected)
    else
        sendMessage("HELLO")
    end
end

-- Registra callback de frame (sem callbacks invasivos)
callbacks:add("frame", onFrame)

console:log("")
console:log("  Script carregado! O shiny hunting vai comecar em breve...")
console:log("  Acompanhe o progresso aqui no console do mGBA.")
console:log("")
