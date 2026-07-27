// Keep the `--app-height` CSS variable in sync with the *visual* viewport height.
//
// The app is a fixed full-height column with the composer pinned to its bottom.
// CSS `100vh` refers to the layout viewport, which does NOT shrink when the
// mobile on-screen keyboard opens — so a `100vh` app renders its input bar
// behind the keyboard (you can type but can't see what you type). The
// VisualViewport API is the only signal that reliably reflects the keyboard on
// iOS Safari, so we mirror its height into a CSS variable the layout consumes.
export function installAppHeight(target: Window = window): () => void {
  const root = target.document.documentElement;

  const update = () => {
    const vv = target.visualViewport;
    const height = vv ? vv.height : target.innerHeight;
    root.style.setProperty('--app-height', `${Math.round(height)}px`);
  };

  update();

  const vv = target.visualViewport;
  vv?.addEventListener('resize', update);
  vv?.addEventListener('scroll', update);
  target.addEventListener('resize', update);
  target.addEventListener('orientationchange', update);

  return update;
}
