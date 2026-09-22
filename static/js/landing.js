const canvas = document.getElementById('particles');
const ctx = canvas.getContext('2d');
let W, H, pts = [];

function resize() {
  W = window.innerWidth; H = window.innerHeight;
  canvas.width = W; canvas.height = H;
  const count = W < 640 ? 35 : 70;
  pts = Array.from({length: count}, () => ({
    x: Math.random() * W, y: Math.random() * H,
    vx: (Math.random() - .5) * .25, vy: (Math.random() - .5) * .25,
    r: Math.random() * 1.4 + .4,
    o: Math.random() * .45 + .08,
    hue: Math.random() > .5 ? 'rgba(255,60,172,' : 'rgba(0,207,255,'
  }));
}
resize();
window.addEventListener('resize', resize);

function draw() {
  ctx.clearRect(0, 0, W, H);
  const connDist = W < 640 ? 70 : 100;
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
      const d = Math.sqrt(dx*dx + dy*dy);
      if (d < connDist) {
        ctx.beginPath();
        ctx.moveTo(pts[i].x, pts[i].y);
        ctx.lineTo(pts[j].x, pts[j].y);
        ctx.strokeStyle = `rgba(255,60,172,${.06 * (1 - d/connDist)})`;
        ctx.lineWidth = .5;
        ctx.stroke();
      }
    }
  }
  pts.forEach(p => {
    p.x += p.vx; p.y += p.vy;
    if (p.x < 0 || p.x > W) p.vx *= -1;
    if (p.y < 0 || p.y > H) p.vy *= -1;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = p.hue + p.o + ')';
    ctx.fill();
  });
  requestAnimationFrame(draw);
}
draw();

