const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/pe_summary_player.js', 'utf8');
// Execute the actual player initializer, without loading the unrelated PDF renderer.
const audioSource = source.slice(source.indexOf('(() => {') + 8, source.indexOf('  document.querySelectorAll'));
function setup(hasAudio = true) {
  const handlers = {};
  const attrs = {};
  const player = { loop: false, paused: true, src: 'first.wav', playCalls: 0,
    play() { this.playCalls++; return Promise.resolve(); } };
  const select = { value: 'second.mp3', addEventListener: (event, fn) => { handlers[event] = fn; } };
  const repeat = { textContent: '반복재생 켜기', setAttribute: (name, value) => { attrs[name] = value; },
    addEventListener: (event, fn) => { handlers[event] = fn; } };
  const elements = hasAudio ? { summary_audio: player, audio_select: select, audio_repeat: repeat } : {};
  vm.runInNewContext(audioSource, { document: { getElementById: id => elements[id] || null } });
  return { player, select, repeat, attrs, handlers };
}
test('repeat defaults off and toggles native current-track loop with accessible state', () => {
  const { player, repeat, attrs, handlers } = setup();
  assert.equal(player.loop, false);
  handlers.click();
  assert.equal(player.loop, true);
  assert.equal(attrs['aria-pressed'], 'true');
  assert.equal(repeat.textContent, '반복재생 끄기');
  handlers.click();
  assert.equal(player.loop, false);
  assert.equal(attrs['aria-pressed'], 'false');
  assert.equal(repeat.textContent, '반복재생 켜기');
  assert.equal(player.playCalls, 0);
});
test('switching WAV to MP3 preserves repeat and paused/playing behavior', () => {
  const { player, handlers } = setup();
  handlers.click(); handlers.change();
  assert.equal(player.src, 'second.mp3');
  assert.equal(player.loop, true);
  assert.equal(player.playCalls, 0);
  player.paused = false; handlers.change();
  assert.equal(player.playCalls, 1);
  handlers.click(); handlers.change();
  assert.equal(player.loop, false);
});
test('pages without audio initialize without touching video', () => { setup(false); });
