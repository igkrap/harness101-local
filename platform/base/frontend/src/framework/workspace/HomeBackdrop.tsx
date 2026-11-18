import { useEffect, useRef } from 'react';

type Dot = { ox: number; oy: number; x: number; y: number; vx: number; vy: number };
type Ring = { x: number; y: number; r: number };
const GAP = 24, REACH = 150, SPEED = 9;

/**
 * The home page's living background: a field of dots that leans away from the pointer and lights up around it,
 * with a ripple running out from every click. Purely decorative (hidden from assistive technology), drawn only
 * while something moves, and still for people who ask for reduced motion.
 */
export function HomeBackdrop() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current, host = element?.parentElement;
    const context = element?.getContext('2d');
    if (!element || !host || !context) return;
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let dots: Dot[] = [], rings: Ring[] = [], width = 0, height = 0, frame = 0, running = false;
    const pointer = { x: -9999, y: -9999, inside: false };
    const colours = () => { const style = getComputedStyle(document.documentElement);
      return { accent: style.getPropertyValue('--fw-accent').trim() || '#2d72d2', dark: document.documentElement.dataset.theme === 'dark' }; };
    let look = colours();

    function layout() {
      const box = host!.getBoundingClientRect(), ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = box.width; height = box.height;
      element!.width = Math.round(width * ratio); element!.height = Math.round(height * ratio);
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
      dots = [];
      for (let y = GAP / 2; y < height; y += GAP) for (let x = GAP / 2; x < width; x += GAP) dots.push({ ox: x, oy: y, x, y, vx: 0, vy: 0 });
      look = colours();
      draw();
    }
    function draw() {
      context!.clearRect(0, 0, width, height);
      const quiet = look.dark ? 'rgba(255,255,255,0.13)' : 'rgba(28,33,39,0.15)';
      let moving = false;
      for (const dot of dots) {
        // Pushed away by the pointer and by each passing ripple, pulled back to its place.
        let near = 0;
        if (pointer.inside) {
          const dx = dot.x - pointer.x, dy = dot.y - pointer.y, distance = Math.hypot(dx, dy) || 1;
          if (distance < REACH) { near = 1 - distance / REACH; const push = near * near * 1.6; dot.vx += (dx / distance) * push; dot.vy += (dy / distance) * push; }
        }
        for (const ring of rings) {
          const dx = dot.ox - ring.x, dy = dot.oy - ring.y, distance = Math.hypot(dx, dy) || 1, off = Math.abs(distance - ring.r);
          if (off < 26) { const lift = (1 - off / 26) * Math.max(0, 1 - ring.r / 620); near = Math.max(near, lift); dot.vx += (dx / distance) * lift * 1.1; dot.vy += (dy / distance) * lift * 1.1; }
        }
        dot.vx += (dot.ox - dot.x) * 0.09; dot.vy += (dot.oy - dot.y) * 0.09;
        dot.vx *= 0.78; dot.vy *= 0.78;
        dot.x += dot.vx; dot.y += dot.vy;
        if (Math.abs(dot.vx) + Math.abs(dot.vy) > 0.02 || Math.abs(dot.x - dot.ox) + Math.abs(dot.y - dot.oy) > 0.05) moving = true;
        context!.beginPath();
        context!.arc(dot.x, dot.y, 1 + near * 2.2, 0, Math.PI * 2);
        if (near > 0.02) { context!.globalAlpha = 0.25 + near * 0.75; context!.fillStyle = look.accent; } else { context!.globalAlpha = 1; context!.fillStyle = quiet; }
        context!.fill();
      }
      context!.globalAlpha = 1;
      // A soft glow follows the pointer so the lit dots sit in a pool of the accent colour.
      if (pointer.inside) {
        const glow = context!.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, REACH * 1.3);
        glow.addColorStop(0, look.accent + '26'); glow.addColorStop(1, look.accent + '00');
        context!.fillStyle = glow; context!.fillRect(pointer.x - REACH * 1.3, pointer.y - REACH * 1.3, REACH * 2.6, REACH * 2.6);
      }
      for (const ring of rings) ring.r += SPEED;
      rings = rings.filter(ring => ring.r < 640);
      return moving || rings.length > 0;
    }
    function loop() { running = draw() || pointer.inside; if (running) frame = requestAnimationFrame(loop); }
    function wake() { if (!running && !calm) { running = true; frame = requestAnimationFrame(loop); } }
    function place(event: PointerEvent) {
      const box = element!.getBoundingClientRect();
      pointer.x = event.clientX - box.left; pointer.y = event.clientY - box.top;
      pointer.inside = pointer.x >= 0 && pointer.y >= 0 && pointer.x <= box.width && pointer.y <= box.height;
    }
    const move = (event: PointerEvent) => { place(event); wake(); };
    const down = (event: PointerEvent) => { place(event); if (pointer.inside && !calm) { rings.push({ x: pointer.x, y: pointer.y, r: 0 }); wake(); } };
    const away = () => { pointer.inside = false; wake(); };
    const observer = new ResizeObserver(layout);
    observer.observe(host);
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerdown', down, { passive: true });
    document.addEventListener('pointerleave', away);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('pointermove', move); window.removeEventListener('pointerdown', down); document.removeEventListener('pointerleave', away); };
  }, []);
  return <canvas ref={canvas} className="home-field" aria-hidden="true" data-ui="home-field" />;
}
