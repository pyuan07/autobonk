"""Launches installed Chrome with persistent profile and anti-throttling flags."""

from pathlib import Path
from typing import Protocol

from playwright.sync_api import BrowserContext, Playwright

BACKGROUND_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,PageFreeze,Translate,MediaRouter,OptimizationHints",
]

KEEP_FOCUSED_SCRIPT = """
(() => {
  const nativeToString = Function.prototype.toString;
  const cloaked = new WeakMap();
  const cloak = (fn, nativeFn) => {
    if (nativeFn) {
      const nameDesc = Object.getOwnPropertyDescriptor(nativeFn, 'name');
      const lenDesc = Object.getOwnPropertyDescriptor(nativeFn, 'length');
      if (nameDesc) Object.defineProperty(fn, 'name', nameDesc);
      if (lenDesc) Object.defineProperty(fn, 'length', lenDesc);
      cloaked.set(fn, nativeToString.call(nativeFn));
    }
    return fn;
  };
  const patchedToString = cloak(function toString() {
    return cloaked.has(this) ? cloaked.get(this) : nativeToString.call(this);
  }, nativeToString);
  Object.defineProperty(Function.prototype, 'toString', {
    value: patchedToString,
    configurable: true,
    writable: true,
  });

  // Real visibility, captured before the game-facing override below: minimized means muted.
  const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden');
  const visDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState');
  const nativeHasFocus = Document.prototype.hasFocus;
  const reallyHidden = () => hiddenDesc.get.call(document);

  // Web Audio: every context's `destination` is a master gain node we control.
  const masters = new Set();
  const BaseAC = window.BaseAudioContext || window.AudioContext;
  const destDesc = BaseAC && Object.getOwnPropertyDescriptor(BaseAC.prototype, 'destination');
  const maxChDesc = window.AudioDestinationNode && Object.getOwnPropertyDescriptor(AudioDestinationNode.prototype, 'maxChannelCount');
  if (destDesc && destDesc.get) {
    const masterOf = new WeakMap();
    Object.defineProperty(BaseAC.prototype, 'destination', {
      configurable: true,
      enumerable: destDesc.enumerable,
      get: cloak(function() {
        const real = destDesc.get.call(this);
        if (window.OfflineAudioContext && this instanceof OfflineAudioContext) return real;
        let master = masterOf.get(this);
        if (!master) {
          master = this.createGain();
          master.gain.value = reallyHidden() ? 0 : 1;
          master.connect(real);
          Object.defineProperty(master, 'maxChannelCount', {
            configurable: true,
            enumerable: maxChDesc ? maxChDesc.enumerable : true,
            get: cloak(function() { return real.maxChannelCount; }, maxChDesc && maxChDesc.get),
          });
          masterOf.set(this, master);
          masters.add(master);
        }
        return master;
      }, destDesc.get),
    });
  }

  // <audio>/<video>: force-mute while hidden, but report the game's own `muted` choice back to it.
  const media = new Set();
  const mutedDesc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'muted');
  const wantedMuted = new WeakMap();
  Object.defineProperty(HTMLMediaElement.prototype, 'muted', {
    configurable: true,
    enumerable: mutedDesc.enumerable,
    get: cloak(function() {
      return wantedMuted.has(this) ? wantedMuted.get(this) : mutedDesc.get.call(this);
    }, mutedDesc.get),
    set: cloak(function(value) {
      wantedMuted.set(this, !!value);
      mutedDesc.set.call(this, !!value || reallyHidden());
    }, mutedDesc.set),
  });
  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = cloak(function(...args) {
    media.add(this);
    if (reallyHidden()) mutedDesc.set.call(this, true);
    return nativePlay.apply(this, args);
  }, nativePlay);

  Object.defineProperty(Document.prototype, 'hidden', {
    configurable: true,
    enumerable: hiddenDesc.enumerable,
    get: cloak(function() { return false; }, hiddenDesc.get),
  });
  Object.defineProperty(Document.prototype, 'visibilityState', {
    configurable: true,
    enumerable: visDesc.enumerable,
    get: cloak(function() { return 'visible'; }, visDesc.get),
  });
  Document.prototype.hasFocus = cloak(function() { return true; }, nativeHasFocus);

  const swallowWindowOrDoc = (event) => {
    if (event.target === window || event.target === document) {
      event.stopImmediatePropagation();
    }
  };

  // requestAnimationFrame that keeps ticking while minimized. Native rAF drives frames whenever
  // the window is not minimized; a worker/timer fallback activates only while reallyHidden().
  const origRAF = window.requestAnimationFrame;
  const origCAF = window.cancelAnimationFrame;
  const nativeRAF = origRAF.bind(window);
  const FALLBACK_MS = 20;
  const pending = new Map();
  let nextId = 0;
  let lastFrameAt = 0;
  let nativeId = 0;
  let timerId = 0;
  let worker = null;

  const flush = (timestamp) => {
    clearTimeout(timerId);
    timerId = 0;
    if (pending.size === 0) return;
    lastFrameAt = Math.max(lastFrameAt, typeof timestamp === 'number' ? timestamp : performance.now());
    const batch = Array.from(pending.values());
    pending.clear();
    for (const callback of batch) {
      try {
        callback(lastFrameAt);
      } catch (err) {
        setTimeout(() => { throw err; }, 0);
      }
    }
    if (pending.size > 0) schedule();
  };

  const startWorker = () => {
    if (worker !== null || !location.protocol.startsWith('http')) return;
    try {
      const url = URL.createObjectURL(new Blob([`setInterval(() => postMessage(0), ${FALLBACK_MS})`]));
      worker = new Worker(url);
      URL.revokeObjectURL(url);
      worker.onmessage = () => {
        if (reallyHidden() && pending.size > 0 && performance.now() - lastFrameAt >= FALLBACK_MS) {
          flush(performance.now());
        }
      };
    } catch (err) {
      worker = false;  // blocked by CSP: the setTimeout fallback still runs
    }
  };

  const onNativeFrame = (timestamp) => {
    nativeId = 0;
    flush(timestamp);
  };

  const schedule = () => {
    if (!nativeId) nativeId = nativeRAF(onNativeFrame);
    if (reallyHidden()) {
      startWorker();
      if (!timerId) {
        const delay = Math.max(0, FALLBACK_MS - (performance.now() - lastFrameAt));
        timerId = setTimeout(() => flush(performance.now()), delay);
      }
    }
  };

  const onVisibilityChange = () => {
    const hidden = reallyHidden();
    for (const master of masters) master.gain.value = hidden ? 0 : 1;
    for (const el of media) {
      mutedDesc.set.call(el, hidden || !!wantedMuted.get(el));
      if (el.paused) media.delete(el);  // play() re-registers it
    }
    if (hidden && pending.size > 0) schedule();
  };
  // Registered before the visibilitychange swallower below, so it still sees the real event.
  window.addEventListener('visibilitychange', onVisibilityChange, true);

  for (const type of ['blur', 'focus', 'visibilitychange', 'freeze', 'pagehide']) {
    window.addEventListener(type, swallowWindowOrDoc, true);
    document.addEventListener(type, swallowWindowOrDoc, true);
  }

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') {
      event.preventDefault();
      const canvas = document.querySelector('canvas#game') || document.querySelector('canvas');
      if (canvas && document.activeElement !== canvas) {
        canvas.focus();
      }
    }
  }, true);

  window.requestAnimationFrame = cloak(function(callback) {
    if (typeof callback !== 'function') throw new TypeError("Failed to execute 'requestAnimationFrame' on 'Window': The callback provided as parameter 1 is not a function.");
    const id = ++nextId;
    pending.set(id, callback);
    schedule();
    return id;
  }, origRAF);
  window.cancelAnimationFrame = cloak(function(id) {
    pending.delete(id);
  }, origCAF);
})();
"""

WINDOW_CHROME_WIDTH, WINDOW_CHROME_HEIGHT = 16, 140


class BrowserConfig(Protocol):
    @property
    def profile_dir(self) -> Path: ...

    @property
    def viewport_width(self) -> int: ...

    @property
    def viewport_height(self) -> int: ...


def launch(playwright: Playwright, config: BrowserConfig) -> BrowserContext:
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    width, height = config.viewport_width, config.viewport_height
    context = playwright.chromium.launch_persistent_context(
        config.profile_dir,
        channel="chrome",
        headless=False,
        viewport={"width": width, "height": height},
        args=[
            *BACKGROUND_ARGS,
            f"--window-size={width + WINDOW_CHROME_WIDTH},{height + WINDOW_CHROME_HEIGHT}",
        ],
        ignore_default_args=["--enable-automation"],
    )
    context.add_init_script(KEEP_FOCUSED_SCRIPT)
    return context
