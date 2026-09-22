-- ============================================================
-- ★ Shiny Charmander Hunter v1.0 ★
-- Pokemon Fire Red (US) v1.0 — mGBA Automation Script
-- ============================================================
-- COMO USAR:
--   1. Execute shiny_hunter.py no terminal PRIMEIRO
--   2. No mGBA: Tools > Scripting
--   3. Na janela de scripting: File > Load script
--   4. Selecione este arquivo (shiny_hunt.lua)
-- ============================================================

-- ==================== CONFIGURAÇÃO ====================

-- Servidor Python (para coordenação entre instâncias)
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 27015

-- Endereços de memória - Fire Red (US) v1.0 (BPRE Rev 0)
-- A party do jogador começa em 0x02024284
-- Cada Pokemon ocupa 100 bytes (0x64)
-- Offset 0x00 = Personality Value (PV/PID) [u32, não criptografado]
-- Offset 0x04 = OT ID (TID nos 16 bits baixos, SID nos 16 bits altos) [u32, não criptografado]
local ADDR_PARTY_PV   = 0x02024284  -- Personality Value do 1o Pokemon
local ADDR_PARTY_OTID = 0x02024288  -- OT ID do 1o Pokemon

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
local WAIT_AFTER_RESET    = 330   -- 5.5s: espera BIOS + logo Game Freak
local TITLE_MASH_DURATION = 300   -- 5s: mash A/Start na title screen
local CONTINUE_DURATION   = 240   -- 4s: selecionar Continue e carregar
local LOADING_WAIT        = 180   -- 3s: espera o jogo carregar completamente
local MASH_TIMEOUT        = 5400  -- 90s: timeout para pegar Charmander
local PRESS_INTERVAL      = 15    -- Pressionar botão a cada 15 frames (~4x/s)
local PRESS_HOLD_FRAMES   = 3     -- Manter botão pressionado por 3 frames

-- ==================== ESTADOS ====================

local STATE = {
    INIT         = "INIT",
    TITLE_WAIT   = "TITLE_WAIT",
    TITLE_MASH   = "TITLE_MASH",
    CONTINUE     = "CONTINUE",
    LOADING      = "LOADING",
    MASHING      = "MASHING",
    CHECK_SHINY  = "CHECK_SHINY",
    SHINY_FOUND  = "SHINY_FOUND",
    RESETTING    = "RESETTING",
    DONE         = "DONE"
}

-- ==================== VARIÁVEIS GLOBAIS ====================

local currentState   = STATE.INIT
local stateFrames    = 0         -- Frames no estado atual
local totalFrames    = 0         -- Frames totais desde o início
local attempts       = 0         -- Número de tentativas
local prevPV         = 0         -- PV anterior (para detectar transição 0 → valor)
local sock           = nil       -- Socket TCP para o servidor Python
local connected      = false     -- Se está conectado ao servidor
local instanceId     = "?"       -- ID da instância (atribuído pelo servidor)
local shouldStop     = false     -- Se deve parar (shiny encontrado em outra instância)
local lastStateName  = ""        -- Para log de mudança de estado

-- ==================== FUNÇÕES UTILITÁRIAS ====================

--- Muda o estado da máquina de estados
local function changeState(newState)
    currentState = newState
    stateFrames = 0
    if newState ~= lastStateName then
        lastStateName = newState
    end
end

--- Verifica se um Pokemon é shiny baseado no PV e OTID
--- Fórmula Gen 3: (PV_high XOR PV_low XOR TID XOR SID) < 8
local function isShiny(pv, otid)
    if pv == 0 then return false end
    local tid = otid & 0xFFFF
    local sid = (otid >> 16) & 0xFFFF
    local p1 = (pv >> 16) & 0xFFFF
    local p2 = pv & 0xFFFF
    local xorVal = p1 ~ p2 ~ tid ~ sid
    return xorVal < 8
end

--- Lê o Personality Value do primeiro Pokemon da party (com proteção)
local function readPV()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_PV) end)
    if ok and val then return val end
    return 0
end

--- Lê o OT ID do primeiro Pokemon da party (com proteção)
local function readOTID()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_OTID) end)
    if ok and val then return val end
    return 0
end

--- Pressiona uma tecla do GBA
local function pressKey(key)
    pcall(function() emu:addKey(key) end)
end

--- Solta todas as teclas
local function releaseAll()
    pcall(function() emu:setKeys(0) end)
end

--- Formata um número como hexadecimal de 8 dígitos
local function hex(val)
    return string.format("0x%08X", val or 0)
end

-- ==================== FUNÇÕES DE SOCKET ====================

--- Tenta conectar ao servidor Python
local function connectToServer()
    if not socket then
        console:log("[Socket] Modulo 'socket' nao disponivel - modo standalone")
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
        console:log("[Socket] Nao foi possivel conectar (modo standalone ativo)")
        console:log("[Socket] O script continuara funcionando normalmente!")
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
        console:log("[Socket] Conexao perdida: " .. tostring(err))
    end
end

--- Verifica mensagens do servidor (non-blocking)
local function checkServerMessages()
    if not connected or not sock then return end

    -- pcall retorna (true, result) em sucesso ou (false, errmsg) em erro
    -- sock:receive retorna data em sucesso ou nil,"timeout" sem dados
    local ok, result = pcall(function()
        return sock:receive(256)
    end)

    -- pcall falhou (erro Lua) — ignorar
    if not ok then return end

    -- receive retornou nil (timeout/sem dados) — ignorar
    if not result or type(result) ~= "string" or #result == 0 then return end

    local data = result

    -- Processa comandos do servidor
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
            console:log("[Info] ID da instancia: #" .. instanceId)
        end
    end
end

-- ==================== CALLBACK DE FRAME ====================

local function onFrame()
    totalFrames = totalFrames + 1
    stateFrames = stateFrames + 1

    -- Verificar mensagens do servidor a cada ~1 segundo
    if connected and totalFrames % 60 == 0 then
        checkServerMessages()
    end

    -- Se recebeu sinal para parar, não faz nada
    if shouldStop then
        releaseAll()
        return
    end

    -- ========== MÁQUINA DE ESTADOS ==========

    if currentState == STATE.INIT then
        -- ── Início de uma nova tentativa ──
        attempts = attempts + 1
        prevPV = 0
        releaseAll()

        console:log("========================================")
        console:log("  Tentativa #" .. attempts .. "  (Instancia #" .. instanceId .. ")")
        console:log("========================================")

        sendMessage("ATTEMPT|" .. attempts)
        changeState(STATE.TITLE_WAIT)

    elseif currentState == STATE.TITLE_WAIT then
        -- ── Espera o BIOS boot + logo Game Freak ──
        releaseAll()
        if stateFrames >= WAIT_AFTER_RESET then
            console:log("[State] Title screen - mashing A/Start...")
            changeState(STATE.TITLE_MASH)
        end

    elseif currentState == STATE.TITLE_MASH then
        -- ── Mash A e Start para passar a title screen ──
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKey(KEY_A)
            pressKey(KEY_START)
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        if stateFrames >= TITLE_MASH_DURATION then
            releaseAll()
            console:log("[State] Selecionando Continue...")
            changeState(STATE.CONTINUE)
        end

    elseif currentState == STATE.CONTINUE then
        -- ── Pressiona A para selecionar Continue e carregar o save ──
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        if stateFrames >= CONTINUE_DURATION then
            releaseAll()
            console:log("[State] Aguardando carregamento...")
            changeState(STATE.LOADING)
        end

    elseif currentState == STATE.LOADING then
        -- ── Espera o jogo carregar completamente ──
        releaseAll()
        if stateFrames >= LOADING_WAIT then
            -- Lê o PV inicial (deve ser 0 = party vazia)
            prevPV = readPV()
            if prevPV ~= 0 then
                console:log("[AVISO] PV inicial nao-zero: " .. hex(prevPV))
                console:log("[AVISO] O save pode ja ter um Pokemon na party!")
                console:log("[AVISO] Verificando se eh shiny mesmo assim...")
                changeState(STATE.CHECK_SHINY)
            else
                console:log("[State] Interagindo com a Pokeball do Charmander...")
                changeState(STATE.MASHING)
            end
        end

    elseif currentState == STATE.MASHING then
        -- ── Mash A para interagir com a Pokeball e aceitar o Charmander ──
        -- Monitora o PV a cada frame para detectar quando o Pokemon é recebido

        local currentPV = readPV()

        -- Detecta transição: PV foi de 0 → não-zero = Pokemon recebido!
        if currentPV ~= 0 and prevPV == 0 then
            releaseAll()
            console:log("")
            console:log("[!!!] Pokemon recebido!")
            console:log("[!!!] PV = " .. hex(currentPV))
            changeState(STATE.CHECK_SHINY)
            return
        end
        prevPV = currentPV

        -- Pressiona A em intervalos regulares
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        -- Timeout de segurança
        if stateFrames >= MASH_TIMEOUT then
            releaseAll()
            console:log("[AVISO] Timeout no mashing! Resetando...")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.CHECK_SHINY then
        -- ── Lê o PV e OTID e verifica se é shiny ──
        local pv   = readPV()
        local otid = readOTID()

        if pv == 0 then
            console:log("[AVISO] PV = 0 durante check. Pode ter sido um falso positivo.")
            console:log("[AVISO] Resetando...")
            changeState(STATE.RESETTING)
            return
        end

        local tid    = otid & 0xFFFF
        local sid    = (otid >> 16) & 0xFFFF
        local p1     = (pv >> 16) & 0xFFFF
        local p2     = pv & 0xFFFF
        local xorVal = p1 ~ p2 ~ tid ~ sid

        console:log("  PV:       " .. hex(pv))
        console:log("  OTID:     " .. hex(otid))
        console:log("  TID:      " .. tid)
        console:log("  SID:      " .. sid)
        console:log("  XOR:      " .. xorVal .. " (shiny se < 8)")

        if isShiny(pv, otid) then
            console:log("")
            changeState(STATE.SHINY_FOUND)
        else
            console:log("  Resultado: NAO shiny")
            console:log("")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.SHINY_FOUND then
        -- ── SHINY ENCONTRADO! ──
        releaseAll()

        local pv   = readPV()
        local otid = readOTID()

        console:log("*********************************************************")
        console:log("*                                                       *")
        console:log("*     ★ ★ ★  SHINY CHARMANDER ENCONTRADO!!!  ★ ★ ★     *")
        console:log("*                                                       *")
        console:log("*********************************************************")
        console:log("")
        console:log("  Instancia: #" .. instanceId)
        console:log("  Tentativa: #" .. attempts)
        console:log("  PV:        " .. hex(pv))
        console:log("  OTID:      " .. hex(otid))
        console:log("")

        -- Salva o save state no slot 1
        local ok, result = pcall(function()
            return emu:saveStateSlot(1)
        end)

        -- pcall sucesso e retorno não é explicitamente false = save OK
        if ok and result ~= false then
            console:log("  Save state salvo no Slot 1!")
        else
            console:log("  [AVISO] Nao foi possivel salvar o state no slot 1")
            -- Tenta salvar em arquivo como fallback
            pcall(function()
                emu:saveStateFile("shiny_charmander.ss1")
                console:log("  Save state salvo como 'shiny_charmander.ss1'")
            end)
        end

        console:log("")
        console:log("  Voce pode carregar o save state e continuar jogando!")
        console:log("")

        -- Notifica o servidor Python
        sendMessage("SHINY|" .. hex(pv) .. "|" .. hex(otid) .. "|" .. attempts)

        changeState(STATE.DONE)

    elseif currentState == STATE.RESETTING then
        -- ── Espera alguns frames e reseta ──
        releaseAll()
        if stateFrames >= 30 then
            sendMessage("RESET|" .. attempts)
            pcall(function() emu:reset() end)
            prevPV = 0
            changeState(STATE.INIT)
        end

    elseif currentState == STATE.DONE then
        -- ── Fim! Nada mais a fazer ──
        releaseAll()
    end
end

-- ==================== INICIALIZAÇÃO ====================

console:log("")
console:log("=========================================================")
console:log("  ★  Shiny Charmander Hunter v1.0")
console:log("  Pokemon Fire Red (US) v1.0")
console:log("=========================================================")
console:log("")
console:log("  Enderecos de memoria:")
console:log("    Party PV:   " .. hex(ADDR_PARTY_PV))
console:log("    Party OTID: " .. hex(ADDR_PARTY_OTID))
console:log("")

-- Tenta conectar ao servidor Python
connectToServer()
if connected then
    sendMessage("HELLO")
end

-- Registra o callback de frame
callbacks:add("frame", onFrame)

console:log("")
console:log("  Script carregado! O shiny hunting vai comecar em breve...")
console:log("  Acompanhe o progresso aqui no console do mGBA.")
console:log("")
