(() => {
  const files = document.querySelector("#files");
  const lyrics = document.querySelector("[data-new-media-lyrics]");
  if (!files || !lyrics) return;

  const updateLyricsVisibility = () => {
    lyrics.hidden = !Array.from(files.files).some((file) => /\.(mp3|wav|mp4)$/i.test(file.name));
  };

  files.addEventListener("change", updateLyricsVisibility);
  updateLyricsVisibility();
})();
