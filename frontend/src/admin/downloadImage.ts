/** Fetch a (CORS-enabled) /media image as a blob and trigger a browser download.
 *  Cross-origin <a download> is ignored by browsers, so we go via a blob URL. */
export async function downloadImage(url: string, filename: string): Promise<void> {
  const res = await fetch(url)
  const blob = await res.blob()
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objUrl)
}
