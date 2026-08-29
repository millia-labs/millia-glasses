-- Millia glasses app. Runs on a Brilliant Halo, and unchanged in halo-emulator.
--
-- The glasses have no network. The phone (or, for the demo, scripts/glasses_host.py)
-- talks to the backend and sends this app what to show. This file only draws.
-- Layout rules come from docs/research/glasses-display-rnd/README.md: white copy,
-- nothing outside the round optic (radius 120 px), a step name wraps, the photo
-- is a thumbnail in the detail view. The rim is a progress ring; copy stays
-- inside it. The room is the largest thing on the glass.
--
-- Messages host -> glass (framed by the vendor's data.lua; codes shared with
-- scripts/glasses_host.py):
--   0x0A ambient view  payload = icon byte .. top .. "\n" .. main .. "\n" .. hint
--   0x0B detail view   same payload; the middle band is left for the sprite
--   0x20 sprite        the vendor's TxSprite (<= 104 px a side, 16 colours)
--   0x0D state         one byte: 0 idle, 1 listening (hollow dot), 2 thinking (pulsing dot)
--   0x0E badge         one byte: 1 on, 0 off - a small amber bell, upper right inside
--                      the optic, over whatever is drawn: the phone got a notification
--   0x0F guest view    a guest at the desk: colour byte (0 white, 1 red, 2 orange,
--                      3 green) .. unit .. "\n" .. name .. "\n" .. requests .. "\n" .. question
--                      - the room large, the guest's name under it, what they asked for in
--                      the middle band, and the open question at the foot in the colour
-- Messages glass -> host:
--   0x0C button        one byte: 1 single, 2 double, 3 long
--
-- Only frame.display, frame.bluetooth, frame.button and frame.sleep are used.

local data = require('data.min')
local sprite = require('sprite.min')

local MSG_AMBIENT = 0x0A
local MSG_DETAIL = 0x0B
local MSG_SPRITE = 0x20
local MSG_BUTTON = 0x0C
local MSG_GUEST = 0x0F

local ICON_NONE, ICON_TICK, ICON_ALERT, ICON_CAMERA, ICON_QUESTION = 0, 1, 2, 3, 4

local WHITE = 0xFFFFFF
local BLACK = 0x000000
local GREEN = 0x22C55E
local AMBER = 0xF59E0B
local RED = 0xEF4444
local ORANGE = 0xF97316
local QUESTION_COLOURS = { [0] = WHITE, [1] = RED, [2] = ORANGE, [3] = GREEN }

local SIZE = 256
local CENTER = 128
local INNER = 110       -- copy stays inside this: the ring owns the rim
local FONT_PX = 16      -- Dogica at 16 px: the smallest size that reads at arm's length
local CHAR_W = 16       -- Dogica is monospace: 8 px per glyph, doubled

local UNIT_Y = 44       -- the room, as large as the optic allows (32, 24 or 16 px)
local UNIT_SIZES = { 32, 24, 16 }
local ICON_Y = 100
local ICON_R = 16
local MAIN_YS = { 128, 152, 176 }
local FOOT_Y = 204      -- "3/7", or what Millia waits for
local RING_OUTER = 119  -- progress: a white arc along the rim, from 12 o'clock, clockwise
local RING_INNER = 114
local THUMB_Y = 72
local THUMB_BAND = 104
local PROMPT_Y = 190
-- The guest view: the room at UNIT_Y (24 px, so the name fits under it), the
-- name, three rows of requests, two rows of question. The question sits at
-- 160/180, not the foot: a 16 px row at y=188 holds 9 glyphs and at 208 only
-- 6 inside the optic (measured 2026-08-29: "Confirm number of towels" drew as
-- "Confirm" / "numb.."). At 160/180 a row holds 12 and 10.
local GUEST_NAME_Y = 78     -- 12 glyphs: "Priya Sharma", "Amira Hassan" whole; longer ends in ".."
local GUEST_ROWS = { 96, 116, 136 }
local GUEST_ASK_YS = { 160, 180 }

-- ---------------------------------------------------------------- geometry

-- Visible width inside the ring across the band y_top..y_bottom.
local function chord(y_top, y_bottom)
    local dy = math.max(math.abs(y_top - CENTER), math.abs(y_bottom - CENTER))
    if dy >= INNER then return 0 end
    return math.floor(2 * math.sqrt(INNER * INNER - dy * dy))
end

local function capacity(y)
    return chord(y, y + FONT_PX) // CHAR_W
end

local function len(s)
    return utf8.len(s) or #s
end

-- Greedy word wrap into the rows given, each row as wide as the optic allows
-- there. A remainder that does not fit ends the last row with ".." - the
-- spoken cue carries the whole sentence, the glass shows what fits.
-- Keep this file ASCII: the upload path encodes it as latin-1.
local function wrap(text, rows)
    local lines = {}
    local words = {}
    for w in text:gmatch('%S+') do words[#words + 1] = w end
    local i = 1
    for r = 1, #rows do
        local cap = capacity(rows[r])
        local line = ''
        while i <= #words do
            local candidate = (line == '') and words[i] or (line .. ' ' .. words[i])
            if len(candidate) > cap then
                if line == '' then
                    -- one word longer than the row: break it
                    line = words[i]:sub(1, cap)
                    words[i] = words[i]:sub(cap + 1)
                end
                break
            end
            line = candidate
            i = i + 1
        end
        lines[r] = line
        if i > #words then break end
    end
    if i <= #words and #lines > 0 then
        local last = lines[#lines]
        local cap = capacity(rows[#lines])
        lines[#lines] = last:sub(1, math.max(0, cap - 2)) .. '..'
    end
    return lines
end

-- ---------------------------------------------------------------- drawing

local function centered(text, y, bold, px, colour)
    if text == nil or text == '' then return end
    px = px or FONT_PX
    frame.display.set_font(bold and 1 or 0, px, 1)
    local x = (SIZE - len(text) * px) // 2 + 1
    frame.display.text(text, x, y, colour or WHITE)
end

-- "0712  3/7" -> "0712", 3, 7. The host packs the top line this way; a top
-- line with no progress is the room alone.
local function parse_top(top)
    local unit, done, total = top:match('^(%S*)%s*(%d+)/(%d+)$')
    if unit == nil then return top, nil, nil end
    return unit, tonumber(done), tonumber(total)
end

-- The room, as large as the band at UNIT_Y can hold.
local function draw_unit(unit, max_px)
    if unit == nil or unit == '' then return end
    for _, px in ipairs(UNIT_SIZES) do
        if px <= (max_px or 32) and len(unit) * px <= chord(UNIT_Y, UNIT_Y + px) then
            centered(unit, UNIT_Y, true, px)
            return
        end
    end
    centered(unit, UNIT_Y, true, FONT_PX)
end

-- Progress as an arc on the rim: from 12 o'clock, clockwise, `done` of `total`.
-- Drawn in 15-degree pieces of at most 8 points each: the firmware's polygon
-- takes 64 numbers at most.
local function arc_point(r, deg)
    local a = math.rad(deg - 90)
    return CENTER + 1 + math.floor(r * math.cos(a) + 0.5), CENTER + 1 + math.floor(r * math.sin(a) + 0.5)
end

local function draw_ring(done, total)
    if done == nil or total == nil or total == 0 then return end
    local sweep = 360 * math.min(done, total) / total
    local from = 0
    while from < sweep do
        local to = math.min(from + 15, sweep)
        local pts = {}
        for _, d in ipairs({ from, from + (to - from) / 3, from + 2 * (to - from) / 3, to }) do
            local x, y = arc_point(RING_OUTER, d)
            pts[#pts + 1] = x; pts[#pts + 1] = y
        end
        for _, d in ipairs({ to, from + 2 * (to - from) / 3, from + (to - from) / 3, from }) do
            local x, y = arc_point(RING_INNER, d)
            pts[#pts + 1] = x; pts[#pts + 1] = y
        end
        frame.display.polygon(pts, WHITE)
        from = to
    end
end

local function draw_icon(kind)
    local cx, cy, r = CENTER, ICON_Y, ICON_R
    if kind == ICON_TICK then
        frame.display.circle(cx, cy, r, GREEN, true)
        frame.display.polygon({
            cx - r // 2, cy,
            cx - r // 2 + 4, cy - 4,
            cx - r // 8, cy + r // 3,
            cx + r // 2, cy - r // 2,
            cx + r // 2 + 4, cy - r // 2 + 4,
            cx - r // 8, cy + r // 3 + 8,
        }, BLACK)
    elseif kind == ICON_ALERT then
        frame.display.circle(cx, cy, r, AMBER, true)
        frame.display.rect(cx - 2, cy - 12, 5, 15, BLACK, true)
        frame.display.rect(cx - 2, cy + 6, 5, 5, BLACK, true)
    elseif kind == ICON_CAMERA then
        frame.display.rect(cx - r, cy - r + 6, 2 * r, 2 * r - 10, WHITE, true)
        frame.display.rect(cx - 6, cy - r + 2, 12, 5, WHITE, true)
        frame.display.circle(cx, cy + 1, 8, BLACK, true)
        frame.display.circle(cx, cy + 1, 4, WHITE, true)
    elseif kind == ICON_QUESTION then
        frame.display.circle(cx, cy, r, WHITE, true)
        frame.display.set_font(1, FONT_PX, 1)
        frame.display.text('?', cx - CHAR_W // 2 + 1, cy - 7, BLACK)
    end
end

local function parse_view(payload)
    local icon = string.byte(payload, 1) or ICON_NONE
    local body = payload:sub(2)
    local lines = {}
    for line in (body .. '\n'):gmatch('(.-)\n') do lines[#lines + 1] = line end
    return icon, lines[1] or '', lines[2] or '', lines[3] or ''
end

local detail_pending = false

-- The ambient view: the room large at the top, the step in the middle band,
-- progress as the ring and as "3/7" at the foot. The foot gives way to what
-- Millia is waiting for ("yes?", "how many?") while she waits.
local function draw_ambient(payload)
    local icon, top, main, hint = parse_view(payload)
    local unit, done, total = parse_top(top)
    detail_pending = false
    frame.display.clear(BLACK)
    draw_ring(done, total)
    draw_unit(unit)
    draw_icon(icon)
    local rows = wrap(main, MAIN_YS)
    for r = 1, #rows do centered(rows[r], MAIN_YS[r], true) end
    if hint ~= '' then
        centered(hint, FOOT_Y, false)
    elseif done ~= nil then
        centered(done .. '/' .. total, FOOT_Y, false)
    end
end

local function draw_detail(payload)
    local _, top, _, hint = parse_view(payload)
    local unit, done, total = parse_top(top)
    detail_pending = true
    frame.display.clear(BLACK)
    draw_ring(done, total)
    draw_unit(unit, 24)
    centered(hint, PROMPT_Y, true)
end

-- A guest at the desk. Nothing is spoken; the glass is the whole reply.
local function draw_guest(payload)
    local colour = QUESTION_COLOURS[string.byte(payload, 1) or 0] or WHITE
    local body = payload:sub(2)
    local lines = {}
    for line in (body .. '\n'):gmatch('(.-)\n') do lines[#lines + 1] = line end
    local unit, name, requests, question = lines[1] or '', lines[2] or '', lines[3] or '', lines[4] or ''
    detail_pending = false
    frame.display.clear(BLACK)
    draw_unit(unit, 24)
    local who = wrap(name, { GUEST_NAME_Y })  -- a long name ends in "..", never off the rim
    centered(who[1], GUEST_NAME_Y, false)
    local rows = wrap(requests, GUEST_ROWS)
    for r = 1, #rows do centered(rows[r], GUEST_ROWS[r], true) end
    local ask = wrap(question, GUEST_ASK_YS)
    for r = 1, #ask do centered(ask[r], GUEST_ASK_YS[r], true, nil, colour) end
end

local function draw_sprite(payload)
    local s = sprite.parse_sprite(payload)
    if s.compressed then return end  -- the host sends plain sprites
    sprite.set_palette(s.num_colors, s.palette_data)
    local x = (SIZE - s.width) // 2 + 1
    local y = THUMB_Y + (THUMB_BAND - s.height) // 2 + 1
    frame.display.bitmap(x, y, s.width, s.num_colors, 0, s.pixel_data)
end

-- The state dot, under the hint: hollow while the wearer speaks (listening),
-- pulsing while the backend works (thinking), gone when the cue is drawn.
local MSG_STATE = 0x0D
local STATE_IDLE, STATE_LISTENING, STATE_THINKING = 0, 1, 2
local DOT_Y = 236
local DOT_R = 4
local state = STATE_IDLE
local pulse_on = false
local ticks = 0

local function draw_dot(on, hollow)
    frame.display.circle(CENTER, DOT_Y, DOT_R + 1, BLACK, true)
    if on then
        frame.display.circle(CENTER, DOT_Y, DOT_R, WHITE, not hollow)
    end
end

local function set_state(payload)
    state = string.byte(payload, 1) or STATE_IDLE
    ticks = 0
    pulse_on = true
    if state == STATE_LISTENING then
        draw_dot(true, true)
    elseif state == STATE_THINKING then
        draw_dot(true, false)
    else
        draw_dot(false, false)
    end
end

local function pulse()
    if state ~= STATE_THINKING then return end
    ticks = ticks + 1
    if ticks % 8 == 0 then  -- every 400 ms at the 50 ms loop
        pulse_on = not pulse_on
        draw_dot(pulse_on, false)
    end
end

-- The badge: a small amber bell, upper right inside the optic, drawn over the
-- view and cleared without disturbing it. Silent. It says only: the phone got
-- a notification (Ryan, 2026-08-28: a spoken notice broke the flow).
local MSG_BADGE = 0x0E
local BADGE_X, BADGE_Y, BADGE_R = 196, 96, 9

-- A bell: the dome, the rim, the clapper. Amber, 20 px tall, nothing else.
local function draw_badge(on)
    frame.display.rect(BADGE_X - BADGE_R - 2, BADGE_Y - BADGE_R - 2, 2 * BADGE_R + 5, 2 * BADGE_R + 5, BLACK, true)
    if on then
        frame.display.circle(BADGE_X, BADGE_Y - 2, 6, AMBER, true)          -- the dome
        frame.display.rect(BADGE_X - 6, BADGE_Y - 2, 13, 6, AMBER, true)     -- its sides
        frame.display.rect(BADGE_X - 8, BADGE_Y + 4, 17, 2, AMBER, true)     -- the rim
        frame.display.circle(BADGE_X, BADGE_Y + 8, 2, AMBER, true)          -- the clapper
        frame.display.rect(BADGE_X - 1, BADGE_Y - 9, 3, 2, AMBER, true)      -- the crown
    end
end

local function handle(code, payload)
    if code == MSG_AMBIENT then
        state = STATE_IDLE
        draw_ambient(payload)
    elseif code == MSG_DETAIL then
        state = STATE_IDLE
        draw_detail(payload)
    elseif code == MSG_GUEST then
        state = STATE_IDLE
        draw_guest(payload)
    elseif code == MSG_SPRITE then
        draw_sprite(payload)
    elseif code == MSG_STATE then
        set_state(payload)
    elseif code == MSG_BADGE then
        draw_badge((string.byte(payload, 1) or 0) == 1)
    end
end

-- ---------------------------------------------------------------- input

local function send_button(kind)
    pcall(frame.bluetooth.send, string.char(MSG_BUTTON, kind))
end

frame.button.single(function() send_button(1) end)
frame.button.double(function() send_button(2) end)
frame.button.long(function() send_button(3) end)

-- ---------------------------------------------------------------- main loop

frame.display.clear(BLACK)
centered('Millia', MAIN_YS[1], true, 24)

while true do
    local items = data.process_raw_items()
    for i = 1, #items do
        local ok, err = pcall(handle, items[i][1], items[i][2])
        if not ok then print('glasses app error: ' .. tostring(err)) end
    end
    pulse()
    frame.sleep(0.05)
end
