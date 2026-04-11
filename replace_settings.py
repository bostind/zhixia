import re

path = r'e:\Users\bob\Documents\BobBase\aizsk\zhixia\src\App.tsx'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

old_start = '''                <div className="settings-header">
                  <h3>设置</h3>
                  <button className="settings-close" onClick={() => setShowSettings(false)}>✕</button>
                </div>
                <div className="settings-body">'''

start = text.find(old_start)
if start == -1:
    print('start not found')
    exit(1)

body_start = start + len(old_start)
remainder = text[body_start:]
m = re.search(r'\n                </div>\n              </div>', remainder)
if not m:
    print('end not found')
    exit(1)

end = body_start + m.start()
new_block = '''                <div className="settings-header">
                  <h3>设置</h3>
                  <button className="settings-close" onClick={() => setShowSettings(false)}>✕</button>
                </div>
                <SettingsPanel
                  status={status}
                  settingsBusy={settingsBusy}
                  newDir={newDir}
                  setNewDir={setNewDir}
                  handleAddDir={handleAddDir}
                  handleRemoveDir={handleRemoveDir}
                  llmSettings={llmSettings}
                  setLlmSettings={setLlmSettings}
                  saveLlmSettings={saveLlmSettings}
                  llmSettingsLoading={llmSettingsLoading}
                  ingestProgress={ingestProgress}
                  reindexing={reindexing}
                  handleReindex={handleReindex}
                  openFolder={openFolder}
                  showToast={showToast}
                />'''

new_text = text[:start] + new_block + text[end:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(new_text)
print('done')
