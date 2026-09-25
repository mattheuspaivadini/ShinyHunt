-- ============================================================
-- Hunter Shiny v1.0 — Magikarp (Rota 4 - Deteccao de Slot Livre)
-- Pokemon Fire Red (US) v1.0 — mGBA Automation Script
-- ============================================================
-- COMO USAR:
--   1. No jogo, posicione seu personagem em frente ao vendedor
--      de Magikarp no Centro Pokemon da Rota 4 (preco: 500 moedas).
--   2. Certifique-se de ter pelo menos 1 slot livre na sua party
--      (o script detecta automaticamente o primeiro slot disponivel).
--   3. Salve o jogo pelo menu (Start > Save) exatamente nessa posicao.
--   4. Execute shiny_hunter.py (GUI ou CLI).
--   5. No mGBA: Tools > Scripting > File > Load script.
--   6. Selecione este arquivo (shiny_magi.lua).
-- ============================================================

-- ============================================================
-- MODO DE TESTE / DEBUG RAPIDO:
-- Para testar o fluxo de compra, deteccao de slot e salvamento
-- sem esperar a probabilidade real (1/8192), mude para true:
local DEBUG_FORCE_SHINY = false          -- true = forca deteccao de shiny para teste
local DEBUG_FORCE_SHINY_ATTEMPT = 2      -- tentativa em que o shiny sera simulado
-- ============================================================

-- ==================== CONFIGURACAO DO ALVO ====================

-- ID pre-definido caso este script tenha sido gerado para uma instancia especifica
local SCRIPT_INSTANCE_ID = SCRIPT_INSTANCE_ID or nil

-- Servidor Python (para coordenacao entre instancias)
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 27015

-- Enderecos de memoria - Fire Red (US) v1.0 (BPRE Rev 0)
-- A party do jogador comeca em 0x02024284
-- Cada Pokemon ocupa 100 bytes (0x64)
-- Offset 0x00 = Personality Value (PV/PID) [u32, nao criptografado]
-- Offset 0x04 = OT ID (TID nos 16 bits baixos, SID nos 16 bits altos) [u32, nao criptografado]
local PARTY_BASE_ADDR = 0x02024284
local POKEMON_SIZE    = 100  -- 0x64 bytes por Pokemon

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
local MASH_TIMEOUT        = 5400  -- 90s: timeout para comprar Magikarp
local PRESS_INTERVAL      = 15    -- Pressionar botao a cada 15 frames (~4x/s)

-- Atraso extra maximo (em frames) sorteado a cada tentativa (garante variacao de RNG)
local TITLE_EXTRA_MAX     = 180   -- ate 3s a mais na title screen (garante nova seed de boot)
local LOADING_EXTRA_MAX   = 180   -- ate 3s a mais apos carregar save (garante novos frames de RNG)
local PRESS_HOLD_FRAMES   = 3     -- Manter botao pressionado por 3 frames

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
local totalFrames    = 0         -- Frames totais desde o inicio
local attempts       = 0         -- Numero de tentativas
local targetSlot     = 0         -- Slot livre detectado dinamicamente (1 a 6)
local prevPV         = 0         -- PV anterior do slot alvo (para detectar 0 -> valor)
local sock           = nil       -- Socket TCP para o servidor Python
local connected      = false     -- Se esta conectado ao servidor
local instanceId     = "?"       -- ID da instancia (atribuido pelo servidor)
local shouldStop     = false     -- Se deve parar (shiny encontrado em outra instancia)
local lastStateName  = ""        -- Para log de mudanca de estado
local titleExtra     = 0         -- sorteado no INIT
local loadingExtra   = 0         -- sorteado no INIT

-- ==================== FUNÇÕES UTILITÁRIAS ====================

--- Formata um numero como hexadecimal de 8 digitos
local function hex(val)
    return string.format("0x%08X", val or 0)
end

--- Detecta o numero real desta instancia atraves de multiplos metodos
local function detectInstanceId()
    -- 1. Definido diretamente no script desta instancia
    if SCRIPT_INSTANCE_ID and type(SCRIPT_INSTANCE_ID) == "number" and SCRIPT_INSTANCE_ID >= 1 and SCRIPT_INSTANCE_ID <= 30 then
        return SCRIPT_INSTANCE_ID
    end

    -- 2. ROM header (offset 0x080000B5 marcado pelo inicializador)
    if emu and type(emu.read8) == "function" then
        local ok, val = pcall(function() return emu:read8(0x080000B5) end)
        if ok and val and val >= 1 and val <= 30 then
            return val
        end
    end

    -- 3. Variavel de ambiente repassada no processo
    if os and type(os.getenv) == "function" then
        local ok, envVal = pcall(function() return os.getenv("SHINY_INSTANCE_ID") end)
        if ok and envVal then
            local num = tonumber(envVal)
            if num and num >= 1 and num <= 30 then
                return num
            end
        end
    end

    -- 4. Arquivo instance_id.txt no diretorio da ROM/instancia
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

--- Verifica se um Pokemon eh shiny baseado no PV e OTID
--- Formula Gen 3: (PV_high XOR PV_low XOR TID XOR SID) < 8
local function isShiny(pv, otid)
    if DEBUG_FORCE_SHINY and attempts >= DEBUG_FORCE_SHINY_ATTEMPT then
        console:log("[DEBUG] Forcando deteccao de Shiny para teste!")
        return true
    end
    if pv == 0 then return false end
    local tid = otid & 0xFFFF
    local sid = (otid >> 16) & 0xFFFF
    local p1 = (pv >> 16) & 0xFFFF
    local p2 = pv & 0xFFFF
    local xorVal = p1 ~ p2 ~ tid ~ sid
    return xorVal < 8
end

--- Le o PV de um slot arbitrario da party (1 a 6)
local function readSlotPV(slot)
    if not slot or slot < 1 or slot > 6 then return 0 end
    local addr = PARTY_BASE_ADDR + (slot - 1) * POKEMON_SIZE
    local ok, val = pcall(function() return emu:read32(addr) end)
    if ok and val then return val end
    return 0
end

--- Le o OT ID de um slot arbitrario da party (1 a 6)
local function readSlotOTID(slot)
    if not slot or slot < 1 or slot > 6 then return 0 end
    local addr = PARTY_BASE_ADDR + (slot - 1) * POKEMON_SIZE + 4
    local ok, val = pcall(function() return emu:read32(addr) end)
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

    local ok, result = pcall(function()
        return sock:receive(256)
    end)

    if not ok or not result or type(result) ~= "string" or #result == 0 then return end

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
            console:log("[Info] ID da instancia confirmado pelo servidor: #" .. instanceId)
            -- Re-semeia o RNG especificamente para esta instancia, evitando colisoes
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

    -- Verificar mensagens do servidor a cada ~1 segundo
    if connected and totalFrames % 60 == 0 then
        checkServerMessages()
    end

    -- Se ainda nao tiver ID definido, tenta detectar novamente periodicamente
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

    -- Se recebeu sinal para parar, nao faz nada
    if shouldStop then
        releaseAll()
        return
    end

    -- ========== MÁQUINA DE ESTADOS ==========

    if currentState == STATE.INIT then
        -- ── Inicio de uma nova tentativa ──
        if attempts == 0 then
            pcall(function() emu:reset() end)   -- boot limpo na 1ª tentativa
        end
        attempts = attempts + 1
        local instOffset = tonumber(instanceId) or 1
        titleExtra   = (math.random(0, TITLE_EXTRA_MAX) + instOffset * 7) % (TITLE_EXTRA_MAX + 1)
        loadingExtra = (math.random(0, LOADING_EXTRA_MAX) + instOffset * 13) % (LOADING_EXTRA_MAX + 1)
        targetSlot   = 0
        prevPV       = 0
        releaseAll()

        console:log("========================================")
        console:log("  Tentativa #" .. attempts .. "  (Instancia #" .. instanceId .. ") - Magikarp Rota 4")
        console:log("  Delays sorteados: title +" .. titleExtra .. " | loading +" .. loadingExtra)
        console:log("========================================")

        sendMessage("ATTEMPT|" .. attempts)
        changeState(STATE.TITLE_WAIT)

    elseif currentState == STATE.TITLE_WAIT then
        -- ── Espera o BIOS boot + logo Game Freak ──
        releaseAll()
        if stateFrames >= WAIT_AFTER_RESET + titleExtra then
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
        -- ── Espera o jogo carregar completamente e busca o primeiro slot livre ──
        releaseAll()
        if stateFrames >= LOADING_WAIT + loadingExtra then
            console:log("[Party] Verificando slots da equipe:")
            local freeSlot = nil
            for s = 1, 6 do
                local spv = readSlotPV(s)
                local isFree = (spv == 0)
                if isFree and freeSlot == nil then
                    freeSlot = s
                end
                local info = isFree and "Vazio" or ("Ocupado (" .. hex(spv) .. ")")
                console:log(string.format("  Slot %d: %s", s, info))
            end

            -- Se todos os 6 slots estiverem ocupados
            if freeSlot == nil then
                console:log("[ERRO] Party cheia! Todos os 6 slots estao ocupados.")
                console:log("[ERRO] Deposite pelo menos 1 Pokemon no PC antes de comprar o Magikarp.")
                changeState(STATE.DONE)
                return
            end

            targetSlot = freeSlot
            prevPV = 0
            console:log(string.format("[Party] Slot livre identificado: #%d (Magikarp sera recebido aqui)", targetSlot))
            console:log("[State] Interagindo com o vendedor de Magikarp (500 moedas)...")
            changeState(STATE.MASHING)
        end

    elseif currentState == STATE.MASHING then
        -- ── Mash A para conversar com o vendedor, aceitar os 500 yen e comprar o Magikarp ──
        -- Monitora o PV do slot livre identificado
        local currentPV = readSlotPV(targetSlot)

        -- Detecta transicao: PV foi de 0 -> nao-zero = Magikarp recebido no slot livre!
        if currentPV ~= 0 and prevPV == 0 then
            releaseAll()
            console:log("")
            console:log(string.format("[!!!] Magikarp recebido no Slot #%d!", targetSlot))
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

        -- Timeout de seguranca
        if stateFrames >= MASH_TIMEOUT then
            releaseAll()
            console:log("[AVISO] Timeout no mashing com o vendedor! Resetando...")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.CHECK_SHINY then
        -- ── Le o PV e OTID do slot onde o Magikarp entrou e verifica se eh shiny ──
        local pv   = readSlotPV(targetSlot)
        local otid = readSlotOTID(targetSlot)

        if pv == 0 then
            console:log(string.format("[AVISO] PV = 0 no Slot #%d durante check. Pode ter sido falso positivo.", targetSlot))
            console:log("[AVISO] Resetando...")
            changeState(STATE.RESETTING)
            return
        end

        local tid    = otid & 0xFFFF
        local sid    = (otid >> 16) & 0xFFFF
        local p1     = (pv >> 16) & 0xFFFF
        local p2     = pv & 0xFFFF
        local xorVal = p1 ~ p2 ~ tid ~ sid

        console:log(string.format("  Slot:     #%d", targetSlot))
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

        local pv   = readSlotPV(targetSlot)
        local otid = readSlotOTID(targetSlot)

        console:log("*********************************************************")
        console:log("*                                                       *")
        console:log("*           SHINY MAGIKARP ENCONTRADO!!!                *")
        console:log("*                                                       *")
        console:log("*********************************************************")
        console:log("")
        console:log("  Instancia: #" .. instanceId)
        console:log("  Tentativa: #" .. attempts)
        console:log(string.format("  Slot:      #%d", targetSlot))
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
            console:log("  [AVISO] Nao foi possivel salvar o state no slot 1")
            pcall(function()
                emu:saveStateFile("shiny_magikarp.ss1")
                console:log("  Save state salvo como 'shiny_magikarp.ss1'")
            end)
        end

        console:log("")
        console:log("  Voce pode carregar o save state e continuar jogando!")
        console:log(string.format("  O Magikarp dourado esta no Slot #%d da sua equipe!", targetSlot))
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
            targetSlot = 0
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
console:log("  Hunter Shiny v1.0 — Magikarp (Rota 4 - Deteccao de Slot Livre)")
console:log("  Pokemon Fire Red (US) v1.0")
console:log("=========================================================")
console:log("")
console:log("  Configuracao do Alvo:")
console:log("    Alvo:             Magikarp (Vendedor Centro Pokemon Rota 4)")
console:log("    Preco:            500 moedas")
console:log("    Deteccao de Slot: Automatico (procura qualquer slot livre na party)")
console:log("")

-- Tenta identificar a instancia localmente antes de conectar
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

-- Tenta conectar ao servidor Python
connectToServer()
if connected then
    if detected then
        sendMessage("HELLO|" .. detected)
    else
        sendMessage("HELLO")
    end
end

-- Registra o callback de frame
callbacks:add("frame", onFrame)

console:log("")
console:log("  Script carregado! O shiny hunting do Magikarp vai comecar...")
console:log("  Acompanhe o progresso aqui no console do mGBA.")
console:log("")
