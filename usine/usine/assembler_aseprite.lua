-- Assemble les images pixel d'un sprite (images.json de fabrique.py) en un vrai fichier Aseprite
-- avec ses tags, puis exporte la planche + le JSON (format attendu par le kit et par Godot).
-- aseprite --batch --script-param dossier=build/sprites/plongeur --script-param sortie=assets/sprites/plongeur \
--          --script-param source=art/source/aseprite/plongeur.aseprite --script assembler_aseprite.lua
local dossier = app.params["dossier"]
local sortie = app.params["sortie"]
local source = app.params["source"]
local f = io.open(dossier .. "/images.json"); local txt = f:read("a"); f:close()
local donnees = json.decode(txt)
local id = donnees.id

-- ordre des tags = ordre d'apparition dans le fichier
local ordre = {}
for nom in txt:gmatch('"([%w_]+)"%s*:%s*%[') do table.insert(ordre, nom) end

local spr = nil
local n = 0
local debut = {}
for _, tag in ipairs(ordre) do
  debut[tag] = n + 1
  for _, png in ipairs(donnees.tags[tag]) do
    local img = Image{ fromFile = png }
    if spr == nil then
      spr = Sprite(img.width, img.height, ColorMode.RGB)
      spr.cels[1].image = img
    else
      local fr = spr:newEmptyFrame()
      spr:newCel(spr.layers[1], fr, img, Point(0, 0))
    end
    n = n + 1
  end
end
for _, tag in ipairs(ordre) do
  local t = spr:newTag(debut[tag], debut[tag] + #donnees.tags[tag] - 1)
  t.name = tag
  -- duree de chaque image (ms) si fabriquer l'a donnee
  if donnees.durees_ms and donnees.durees_ms[tag] then
    for k = debut[tag], debut[tag] + #donnees.tags[tag] - 1 do
      spr.frames[k].duration = donnees.durees_ms[tag] / 1000
    end
  end
end
spr:saveAs(source)
app.command.ExportSpriteSheet{
  ui = false, type = SpriteSheetType.HORIZONTAL,
  textureFilename = sortie .. "/" .. id .. ".png",
  dataFilename = sortie .. "/" .. id .. ".json",
  dataFormat = SpriteSheetDataFormat.JSON_ARRAY, listTags = true }
print("ASEPRITE_OK " .. id .. " : " .. n .. " images, tags " .. table.concat(ordre, ", "))
