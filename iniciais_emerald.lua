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
local TARGET_STARTER = TARGET_STARTER or "treecko"

-- Servidor Python (para coordenacao entre instancias)
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 27015

-- Enderecos de memoria - Pokemon Emerald (US) v1.0 (BPEE Rev 0)
-- A party do jogador em Emerald US comeca em 0x020244EC (gPlayerParty)
-- Cada Pokemon ocupa 100 bytes (0x64)
-- Offset 0x00 = Personality Value (PV/PID) [u32, nao criptografado]
-- Offset 0x04 = OT ID (TID nos 16 bits baixos, SID nos 16 bits altos) [u32, nao criptografado]
local ADDR_PARTY_PV   = 0x020244EC  -- Personality Value do 1o Pokemon
local ADDR_PARTY_OTID = 0x020244F0  -- OT ID do 1o Pokemon

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
local OPEN_BAG_WAIT       = 120   -- ~2.0s: espera animacao de fade e abertura completa da bolsa
local MASH_TIMEOUT        = 3600  -- ~60s: timeout de seguranca
local PRESS_INTERVAL      = 12    -- Pressionar botao a cada 12 frames (~5x/s)
local PRESS_HOLD_FRAMES   = 4     -- Manter botao pressionado por 4 frames

-- Atraso extra maximo (em frames) sorteado a cada tentativa (garante variacao de RNG)
-- Nota para Emerald: o PRNG sempre comeca em seed 0 no boot, entao a variacao
-- de frames (titleExtra e loadingExtra) e VITAL para alcancar diferentes seeds/PIDs!
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
    CONFIRM_CHOICE  = "CONFIRM_CHOICE",
    MASHING         = "MASHING",
    CHECK_SHINY     = "CHECK_SHINY",
    SHINY_FOUND     = "SHINY_FOUND",
    RESETTING       = "RESETTING",
    DONE            = "DONE"
}

-- ==================== NORMALIZAÇÃO DO ALVO ====================

local function getNormalizedStarter(starterStr)
    local s = starterStr

    -- 1. Se starterStr não veio definido ou está vazio, usa TARGET_STARTER global
    if not s or s == "" then
        s = TARGET_STARTER
    end

    -- 2. Tenta ler variável de ambiente repassada pelo processo Python
    if os and type(os.getenv) == "function" then
        local ok, envVal = pcall(function() return os.getenv("SHINY_EMERALD_STARTER") end)
        if ok and envVal and envVal ~= "" then
            s = envVal
        end
    end

    -- 3. Tenta ler de emerald_starter.txt em múltiplos caminhos
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
                    local trimmed = content:gsub("%s+", "")
                    if trimmed ~= "" then
                        s = trimmed
                        break
                    end
                end
            end
        end
    end

    -- 4. Tenta ler de config.json
    if io and type(io.open) == "function" then
        local configCandidates = {
            "config.json",
            "../config.json",
            "../../config.json"
        }
        for _, path in ipairs(configCandidates) do
            local ok, f = pcall(function() return io.open(path, "r") end)
            if ok and f then
                local content = f:read("*all")
                f:close()
                if content and content ~= "" then
                    local val = content:match('"emerald_starter"%s*:%s*"([^"]+)"')
                    if val and val ~= "" then
                        s = val
                        break
                    end
                end
            end
        end
    end

    local clean = string.lower(tostring(s or "treecko")):gsub("%s+", "")
    if clean:find("tree") or clean:find("planta") or clean:find("grass") then
        return "treecko", "Treecko (Planta - Seta Esquerda ◀)"
    elseif clean:find("mud") or clean:find("agua") or clean:find("water") then
        return "mudkip", "Mudkip (Agua - Seta Direita ▶)"
    else
        return "torchic", "Torchic (Fogo - Centro ●)"
    end
end

local normalizedStarter, starterDisplayName = getNormalizedStarter(TARGET_STARTER)

-- ==================== VARIÁVEIS GLOBAIS ====================

local currentState   = STATE.INIT
local stateFrames    = 0         -- Frames no estado atual
local totalFrames    = 0         -- Frames totais desde o inicio
local attempts       = 0         -- Numero de tentativas
local prevPV         = 0         -- PV anterior (para detectar 0 -> valor)
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

--- Le o Personality Value do primeiro Pokemon da party
local function readPV()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_PV) end)
    if ok and val then return val end
    return 0
end

--- Le o OT ID do primeiro Pokemon da party
local function readOTID()
    local ok, val = pcall(function() return emu:read32(ADDR_PARTY_OTID) end)
    if ok and val then return val end
    return 0
end

--- Pressiona uma tecla do GBA (compatibilidade ampla addKey + setKeys bitmask)
local function pressKey(key)
    pcall(function() emu:addKey(key) end)
    pcall(function() emu:setKeys(1 << key) end)
end

--- Solta todas as teclas do GBA
local function releaseAll()
    pcall(function() emu:setKeys(0) end)
    for k = 0, 9 do
        pcall(function() emu:clearKey(k) end)
    end
    pcall(function() emu:clearKeys(0x3FF) end)
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

    -- Se ainda nao tiver ID definido, tenta detectar periodicamente
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

        -- Re-detecta o alvo dinamicamente para garantir que alterações sejam refletidas
        normalizedStarter, starterDisplayName = getNormalizedStarter(TARGET_STARTER)

        -- Variação estocástica para quebrar o RNG determinístico do Emerald
        titleExtra   = (math.random(0, TITLE_EXTRA_MAX) + instOffset * 7) % (TITLE_EXTRA_MAX + 1)
        loadingExtra = (math.random(0, LOADING_EXTRA_MAX) + instOffset * 13) % (LOADING_EXTRA_MAX + 1)
        prevPV = 0
        releaseAll()

        console:log("========================================")
        console:log("  Tentativa #" .. attempts .. "  (Instancia #" .. instanceId .. ")")
        console:log("  Alvo: " .. starterDisplayName)
        console:log("  Delays sorteados: title +" .. titleExtra .. " | loading +" .. loadingExtra)
        console:log("========================================")

        sendMessage("ATTEMPT|" .. attempts)
        changeState(STATE.TITLE_WAIT)

    elseif currentState == STATE.TITLE_WAIT then
        -- ── Espera o BIOS boot + logo Game Freak ──
        releaseAll()
        if stateFrames >= WAIT_AFTER_RESET + titleExtra then
            console:log("[State] Title screen (Rayquaza) - mashing A/Start...")
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
            console:log("[State] Aguardando carregamento do save...")
            changeState(STATE.LOADING)
        end

    elseif currentState == STATE.LOADING then
        -- ── Espera o jogo carregar completamente no mapa ──
        releaseAll()
        if stateFrames >= LOADING_WAIT + loadingExtra then
            -- Le o PV inicial (deve ser 0 = party vazia)
            prevPV = readPV()
            if prevPV ~= 0 then
                console:log("[AVISO] PV inicial nao-zero: " .. hex(prevPV))
                console:log("[AVISO] O save ja possui um Pokemon na party (Slot 1)!")
                console:log("[AVISO] Verificando se e shiny mesmo assim...")
                changeState(STATE.CHECK_SHINY)
            else
                console:log("[State] Interagindo com a bolsa do Prof. Birch...")
                changeState(STATE.OPEN_BAG)
            end
        end

    elseif currentState == STATE.OPEN_BAG then
        -- ── Interage com a bolsa no chão (apenas UMA pressão do botão A!) ──
        -- Pressiona A do frame 5 ao 18 para garantir início da interação
        if stateFrames == 5 then
            pressKey(KEY_A)
        elseif stateFrames == 18 then
            releaseAll()
        end

        -- CRÍTICO: NUNCA pressionar o botão A em nenhum outro frame neste estado!
        -- A animação de abertura da bolsa leva ~50 frames. Se pressionarmos A após ela
        -- abrir, o jogo selecionará instantaneamente o Torchic (que é a posição padrão do meio)!
        -- Aguardamos 120 frames (~2.0s) para que a bolsa esteja 100% aberta, visível e parada.
        if stateFrames >= OPEN_BAG_WAIT then
            releaseAll()
            console:log("[State] Bolsa aberta! Navegando ate: " .. starterDisplayName .. "...")
            changeState(STATE.SELECT_STARTER)
        end

    elseif currentState == STATE.SELECT_STARTER then
        -- ── Move o cursor na bolsa conforme o inicial desejado ──
        -- O cursor padrão do jogo começa no meio: Torchic (index 1)
        if normalizedStarter == "treecko" then
            -- Mover para a esquerda (Treecko = index 0)
            -- Envia 3 pulsos firmes de KEY_LEFT para garantir a movimentação
            if stateFrames == 5 or stateFrames == 25 or stateFrames == 45 then
                pressKey(KEY_LEFT)
            elseif stateFrames == 15 or stateFrames == 35 or stateFrames == 55 then
                releaseAll()
            end

            if stateFrames >= 70 then
                releaseAll()
                console:log("[State] Cursor posicionado em Treecko! Abrindo Pokebola...")
                changeState(STATE.CONFIRM_CHOICE)
            end

        elseif normalizedStarter == "mudkip" then
            -- Mover para a direita (Mudkip = index 2)
            -- Envia 3 pulsos firmes de KEY_RIGHT para garantir a movimentação
            if stateFrames == 5 or stateFrames == 25 or stateFrames == 45 then
                pressKey(KEY_RIGHT)
            elseif stateFrames == 15 or stateFrames == 35 or stateFrames == 55 then
                releaseAll()
            end

            if stateFrames >= 70 then
                releaseAll()
                console:log("[State] Cursor posicionado em Mudkip! Abrindo Pokebola...")
                changeState(STATE.CONFIRM_CHOICE)
            end

        else
            -- Torchic já é a posição central padrão do jogo
            releaseAll()
            if stateFrames >= 30 then
                console:log("[State] Cursor mantido em Torchic! Abrindo Pokebola...")
                changeState(STATE.CONFIRM_CHOICE)
            end
        end

    elseif currentState == STATE.CONFIRM_CHOICE then
        -- ── Pressiona A na Pokebola escolhida para abrir o zoom e a pergunta ──
        if stateFrames == 5 or stateFrames == 25 then
            pressKey(KEY_A)
        elseif stateFrames == 15 or stateFrames == 35 then
            releaseAll()
        end

        -- Aguarda o zoom do circulo branco, cry do Pokemon e o dialogo 'YES / NO'
        if stateFrames >= 75 then
            releaseAll()
            console:log("[State] Confirmando 'SIM' para " .. starterDisplayName .. "...")
            changeState(STATE.MASHING)
        end

    elseif currentState == STATE.MASHING then
        -- ── Mash A para confirmar YES na pergunta e iniciar a batalha ──
        -- Monitora o PV do slot 1 a cada frame
        local currentPV = readPV()

        -- Detecta transicao: PV foi de 0 -> nao-zero = Pokemon gerado!
        if currentPV ~= 0 and prevPV == 0 then
            releaseAll()
            console:log("")
            console:log("[!!!] Pokemon recebido na party (Slot 1)!")
            console:log("[!!!] PV = " .. hex(currentPV))
            changeState(STATE.CHECK_SHINY)
            return
        end
        prevPV = currentPV

        -- Pressiona A em intervalos regulares para confirmar YES
        local cycle = stateFrames % PRESS_INTERVAL
        if cycle == 0 then
            pressKey(KEY_A)
        elseif cycle == PRESS_HOLD_FRAMES then
            releaseAll()
        end

        -- Timeout de seguranca
        if stateFrames >= MASH_TIMEOUT then
            releaseAll()
            console:log("[AVISO] Timeout no mashing da bolsa! Resetando...")
            changeState(STATE.RESETTING)
        end

    elseif currentState == STATE.CHECK_SHINY then
        -- ── Le PV e OTID e calcula o XOR para verificar se e shiny ──
        -- Pequena pausa de seguranca para garantir estabilidade da memoria
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

        if (normalizedStarter == "treecko" and speciesId ~= 277 and speciesId ~= 0) or
           (normalizedStarter == "torchic" and speciesId ~= 280 and speciesId ~= 0) or
           (normalizedStarter == "mudkip" and speciesId ~= 283 and speciesId ~= 0) then
            console:log("  [ALERTA] ATENCAO: Especie obtida (" .. actualName .. ") difere do alvo configurado!")
        end

        local shiny = isShiny(pv, otid)

        -- Simulação para modo de teste
        if DEBUG_FORCE_SHINY and attempts >= DEBUG_FORCE_SHINY_ATTEMPT then
            shiny = true
            console:log("  [DEBUG] Modo de teste ativo: forcando deteccao de Shiny!")
        end

        if shiny then
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

        -- Notifica o servidor Python
        sendMessage("SHINY|" .. hex(pv) .. "|" .. hex(otid) .. "|" .. attempts)

        changeState(STATE.DONE)

    elseif currentState == STATE.RESETTING then
        -- ── Espera alguns frames e reseta o emulador ──
        releaseAll()
        if stateFrames >= 30 then
            sendMessage("RESET|" .. attempts)
            pcall(function() emu:reset() end)
            prevPV = 0
            changeState(STATE.INIT)
        end

    elseif currentState == STATE.DONE then
        -- ── Fim! Mantem estado intacto ──
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

-- Registra o callback de frame do mGBA
callbacks:add("frame", onFrame)

console:log("")
console:log("  Script carregado! O shiny hunting vai comecar em breve...")
console:log("  Acompanhe o progresso aqui no console do mGBA.")
console:log("")
