/* Shared audio player for Nuovissimo Progetto Italiano */
const Player = (() => {
  const audio = new Audio();
  let tracks = [];
  let currentIndex = -1;

  const SVG = {
    play:  `<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M8 5.14v14l11-7-11-7z"/></svg>`,
    pause: `<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`,
    prev:  `<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg>`,
    next:  `<svg viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M6 18l8.5-6L6 6v12zm2-8.14 5.5 3.89L8 17.86V9.86zM16 6h2v12h-2z"/></svg>`,
  };

  function fmt(s) {
    if (!s || isNaN(s)) return '0:00';
    return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  }

  function el(id) { return document.getElementById(id); }

  function refreshBar() {
    const t = tracks[currentIndex];
    const playing = !audio.paused && currentIndex >= 0;
    if (el('player-title'))   el('player-title').textContent  = t ? t.label   : '—';
    if (el('player-section')) el('player-section').textContent = t ? t.section : '';
    if (el('btn-playpause'))  el('btn-playpause').innerHTML   = playing ? SVG.pause : SVG.play;
  }

  function refreshRows() {
    const playing = !audio.paused && currentIndex >= 0;
    document.querySelectorAll('.track-row').forEach((row, i) => {
      const active = i === currentIndex;
      row.classList.toggle('bg-slate-700/80', active);
      row.classList.toggle('bg-slate-800',    !active);
      const btn = row.querySelector('.btn-play');
      if (btn) btn.innerHTML = (active && playing) ? SVG.pause : SVG.play;
    });
  }

  function doPlay(index) {
    if (index < 0 || index >= tracks.length) return;
    if (index === currentIndex && !audio.paused) { audio.pause(); return; }
    if (index !== currentIndex) { currentIndex = index; audio.src = tracks[index].src; }
    audio.play();
    const rows = document.querySelectorAll('.track-row');
    rows[index]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  audio.addEventListener('play',  () => { refreshBar(); refreshRows(); });
  audio.addEventListener('pause', () => { refreshBar(); refreshRows(); });
  audio.addEventListener('ended', () => {
    if (currentIndex < tracks.length - 1) doPlay(currentIndex + 1);
    else { refreshBar(); refreshRows(); }
  });

  audio.addEventListener('timeupdate', () => {
    const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
    if (el('seek-fill'))    el('seek-fill').style.width   = `${pct}%`;
    if (el('time-current')) el('time-current').textContent = fmt(audio.currentTime);
    if (el('time-total'))   el('time-total').textContent   = fmt(audio.duration);
  });

  audio.addEventListener('loadedmetadata', () => {
    if (el('time-total')) el('time-total').textContent = fmt(audio.duration);
  });

  return {
    init(trackList) {
      tracks = trackList;

      // Seek bar click
      el('seek-bar')?.addEventListener('click', e => {
        const r = e.currentTarget.getBoundingClientRect();
        if (audio.duration) audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration;
      });

      // Control buttons
      el('btn-playpause')?.addEventListener('click', () => {
        if (currentIndex < 0) doPlay(0);
        else if (audio.paused) audio.play();
        else audio.pause();
      });
      el('btn-prev')?.addEventListener('click', () => doPlay(currentIndex - 1));
      el('btn-next')?.addEventListener('click', () => doPlay(currentIndex + 1));

      refreshBar();
    },

    play: doPlay,

    renderTracks(containerId, accentClass) {
      const wrap = document.getElementById(containerId);
      if (!wrap) return;
      let lastSection = null;

      tracks.forEach((t, i) => {
        if (t.section !== lastSection) {
          lastSection = t.section;
          const hdr = document.createElement('div');
          hdr.className = 'px-4 py-2.5 text-xs font-bold uppercase tracking-widest text-slate-500 bg-slate-900 sticky top-0 z-10 border-b border-slate-800';
          hdr.textContent = t.section;
          wrap.appendChild(hdr);
        }

        const row = document.createElement('div');
        row.className = 'track-row flex items-center gap-3 px-4 py-3 bg-slate-800 hover:bg-slate-700/80 cursor-pointer border-b border-slate-700/50 transition-colors select-none';
        row.innerHTML = `
          <span class="w-7 text-right text-slate-600 text-xs font-mono shrink-0">${i + 1}</span>
          <button class="btn-play shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                         text-white ${accentClass} transition-colors" title="Riproduci">
            ${SVG.play}
          </button>
          <span class="flex-1 text-sm text-white">${t.label}</span>`;

        row.querySelector('.btn-play').addEventListener('click', e => { e.stopPropagation(); doPlay(i); });
        row.addEventListener('click', () => doPlay(i));
        wrap.appendChild(row);
      });
    }
  };
})();
