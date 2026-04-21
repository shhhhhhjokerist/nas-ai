function escapeHtml(input) {
  return String(input || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

export function openVideoPlayerPopup(videoUrl, title = '视频播放') {
  const popup = window.open('', '_blank', 'popup=yes,width=1024,height=680,resizable=yes,scrollbars=no')
  if (!popup) {
    return false
  }

  const safeTitle = escapeHtml(title)
  const safeUrl = escapeHtml(videoUrl)

  popup.document.write(`
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${safeTitle}</title>
    <style>
      html, body { margin: 0; padding: 0; width: 100%; height: 100%; background: #05070a; color: #fff; }
      .shell { display: flex; flex-direction: column; width: 100%; height: 100%; }
      .topbar { padding: 10px 14px; font: 14px/1.4 "Segoe UI", Arial, sans-serif; color: #d1d5db; border-bottom: 1px solid rgba(255,255,255,0.1); }
      video { width: 100%; height: 100%; background: #000; }
      .player-wrap { flex: 1; min-height: 0; }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="topbar">${safeTitle}</div>
      <div class="player-wrap">
        <video id="popupVideo" src="${safeUrl}" controls autoplay playsinline></video>
      </div>
    </div>
    <script>
      const video = document.getElementById('popupVideo')
      window.addEventListener('beforeunload', () => {
        try {
          video.pause()
          video.removeAttribute('src')
          video.load()
        } catch (e) {
          // no-op
        }
      })
    </script>
  </body>
</html>
  `)
  popup.document.close()
  return true
}

export function openInfoPopup(title, data) {
  const popup = window.open('', '_blank', 'popup=yes,width=760,height=680,resizable=yes,scrollbars=yes')
  if (!popup) {
    return false
  }

  const safeTitle = escapeHtml(title || '文件信息')
  const text = escapeHtml(JSON.stringify(data ?? {}, null, 2))

  popup.document.write(`
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${safeTitle}</title>
    <style>
      html, body { margin: 0; padding: 0; width: 100%; height: 100%; background: #f8fafc; color: #0f172a; }
      .header { padding: 12px 14px; font: 700 14px/1.4 "Segoe UI", Arial, sans-serif; border-bottom: 1px solid #e2e8f0; background: #fff; }
      pre {
        margin: 0;
        padding: 14px;
        box-sizing: border-box;
        width: 100%;
        height: calc(100% - 46px);
        overflow: auto;
        font: 13px/1.6 Consolas, "Courier New", monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <div class="header">${safeTitle}</div>
    <pre>${text}</pre>
  </body>
</html>
  `)
  popup.document.close()
  return true
}
