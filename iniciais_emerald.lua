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
local WAIT_AFTER_RESET    = 360   -- ~6.0s: espera BIOS + intro Game Freak (estrela cadente)
local TITLE_MASH_DURATION = 240   -- ~4.0s: mash A/Start na title screen (Rayquaza)
local CONTINUE_DURATION   = 180   -- ~3.0s: selecionar Continue e carregar o save
local LOADING_WAIT        = 180   -- ~3.0s: espera o jogo carregar no overworld
local MASH_TIMEOUT        = 3600  -- ~60s: timeout de seguranca
local PRESS_INTERVAL      = 12    -- Pressionar botao a cada 12 frames (~5x/s)
local PRESS_HOLD_FRAMES   = 4     -- Manter botao pressionado por 4 frames

-- Atraso extra maximo (em frames) sorteado a cada tentativa (garante variacao de RNG)
local TITLE_EXTRA_MAX     = 180   -- ate 3s a mais na title screen
local LOADING_EXTRA_MAX   = 180   -- ate 3s a mais apos carregar save

-- ==================== ESTADOS ====================

local STATE = {
    INIT            = "INIT",
    TITLE_WAIT      = "TITLE_WAIT",
    TITLE_MASH      = "TITLE_MASH",
    CONTINUE        = "CONTINUE",
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

--- Verifica se a tela da bolsa do Prof. Birch abriu na memoria (SOMENTE LEITURA)
local function isStarterBagOpen()
    local ok, cb2 = pcall(function() return emu:read32(ADDR_MAIN_CALLBACK2) end)
    if ok and cb2 and (cb2 & ~1) == FN_CB2_STARTER_CHOOSE then
        return true
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
    return false
end

--- Le o indice atual da selecao na tela de iniciais (SOMENTE LEITURA)
--- 0 = Treecko, 1 = Torchic, 2 = Mudkip
local function getStarterSelection()
    local ok, sel = pcall(function() return emu:read16(ADDR_TASK0_STARTER) end)
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
        if stateFrames >= WAIT_AFTER_RESET + titleExtra then
            console:log("[State] Title screen (Rayquaza) - mashing A/Start...")
            changeState(STATE.TITLE_MASH)
        end

    elseif currentState == STATE.TITLE_MASH then
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKeys((1 << KEY_A) | (1 << KEY_START))
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        if stateFrames >= TITLE_MASH_DURATION then
            releaseAll()
            console:log("[State] Selecionando Continue...")
            changeState(STATE.CONTINUE)
        end

    elseif currentState == STATE.CONTINUE then
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        if stateFrames >= CONTINUE_DURATION then
            releaseAll()
            console:log("[State] Aguardando carregamento do save...")
            changeState(STATE.LOADING)
        end

    elseif currentState == STATE.LOADING then
        releaseAll()
        if stateFrames >= LOADING_WAIT + loadingExtra then
            -- Armazena o PV que estiver na memoria (0 no save normal) para detectar quando o novo Pokemon for gerado
            initialPV = readPV()
            console:log("[State] Jogo carregado no overworld. Interagindo com a bolsa do Prof. Birch...")
            logToFile("Jogo carregado no overworld. Interagindo com a bolsa...")
            changeState(STATE.OPEN_BAG)
        end

    elseif currentState == STATE.OPEN_BAG then
        -- 1. Se a tela da bolsa já está aberta e a task de input está pronta para ler D-pad:
        if isStarterInputReady() then
            releaseAll()
            console:log("[State] Bolsa aberta e pronta para selecao! Alvo: " .. starterDisplayName)
            logToFile("Bolsa aberta e pronta para selecao: " .. starterDisplayName)
            changeState(STATE.SELECT_STARTER)
            return
        end

        -- 2. Se a bolsa já começou a abrir (fade-in), NUNCA aperte A para não selecionar Torchic acidentalmente!
        if isStarterBagOpen() then
            releaseAll()
            return
        end

        -- 3. No overworld em frente a bolsa, dá UM toque em 'A' a cada 45 frames (~0.75s) para interagir
        local cycle = stateFrames % 45
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == 5 then
            releaseAll()
        end

        -- 4. Timeout de segurança: após 240 frames (~4s), se não detectou por memória, avança
        if stateFrames >= 240 then
            releaseAll()
            console:log("[State] Avancando para a selecao do inicial...")
            changeState(STATE.SELECT_STARTER)
        end

    elseif currentState == STATE.SELECT_STARTER then
        -- Garante uma pausa inicial de 10 frames com teclas soltas para resetar debounce de botões
        if stateFrames < 10 then
            releaseAll()
            return
        end

        local curSel = getStarterSelection()

        -- Se o alvo for MUDKIP (seta para a DIREITA ▶, índice 2):
        if targetIdx == 2 then
            -- Se o cursor do jogo já alcançou o slot 2 (Mudkip):
            if curSel == 2 then
                releaseAll()
                -- Aguarda estabilização do cursor (~35 frames após selecionar)
                if stateFrames >= 45 then
                    console:log("[State] Mudkip selecionado no cursor (slot 2)! Abrindo Pokebola...")
                    logToFile("Mudkip selecionado no cursor (slot 2)! Abrindo Pokebola...")
                    changeState(STATE.OPEN_POKEBALL)
                end
                return
            end

            -- Pulsa D-Pad DIREITA a cada 16 frames até o jogo confirmar que mudou para o slot 2
            local cycle = (stateFrames - 10) % 16
            if cycle == 0 then
                console:log("[Input] Pressionando D-Pad DIREITA para selecionar Mudkip...")
                pressKey(KEY_RIGHT)
            elseif cycle == 6 then
                releaseAll()
            end

        -- Se o alvo for TREECKO (seta para a ESQUERDA ◀, índice 0):
        elseif targetIdx == 0 then
            -- Se o cursor do jogo já alcançou o slot 0 (Treecko):
            if curSel == 0 then
                releaseAll()
                if stateFrames >= 45 then
                    console:log("[State] Treecko selecionado no cursor (slot 0)! Abrindo Pokebola...")
                    logToFile("Treecko selecionado no cursor (slot 0)! Abrindo Pokebola...")
                    changeState(STATE.OPEN_POKEBALL)
                end
                return
            end

            -- Pulsa D-Pad ESQUERDA a cada 16 frames até o jogo confirmar que mudou para o slot 0
            local cycle = (stateFrames - 10) % 16
            if cycle == 0 then
                console:log("[Input] Pressionando D-Pad ESQUERDA para selecionar Treecko...")
                pressKey(KEY_LEFT)
            elseif cycle == 6 then
                releaseAll()
            end

        -- Se o alvo for TORCHIC (centro ●, índice 1):
        else
            releaseAll()
            if stateFrames >= 35 then
                console:log("[State] Torchic mantido no centro (slot 1). Abrindo Pokebola...")
                logToFile("Torchic mantido no centro (slot 1). Abrindo Pokebola...")
                changeState(STATE.OPEN_POKEBALL)
            end
        end

        -- Timeout de segurança: após 180 frames avança
        if stateFrames >= 180 then
            releaseAll()
            changeState(STATE.OPEN_POKEBALL)
        end

    elseif currentState == STATE.OPEN_POKEBALL then
        -- No frame 10, pressiona 'A' para abrir o zoom da Pokébola do inicial selecionado
        if stateFrames == 10 then
            console:log("[State] Abrindo Pokebola de " .. starterDisplayName .. "...")
            pressKey(KEY_A)
        elseif stateFrames == 16 then
            releaseAll()
        end

        -- Aguarda o zoom do círculo branco, o cry e a caixa YES/NO surgirem (~80 frames)
        if stateFrames >= 80 then
            releaseAll()
            console:log("[State] Confirmando 'SIM' para " .. starterDisplayName .. "...")
            logToFile("Confirmando 'SIM' para " .. starterDisplayName)
            changeState(STATE.CONFIRM_CHOICE)
        end

    elseif currentState == STATE.CONFIRM_CHOICE then
        -- Monitora o PV do slot 1: quando for gerado e diferir do inicial, o Pokémon chegou!
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

        -- Pulsa 'A' a cada 10 frames para confirmar 'YES' e passar o dialogo do Birch
        local cycle = stateFrames % 10
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == 4 then
            releaseAll()
        end

        -- Timeout de seguranca
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
