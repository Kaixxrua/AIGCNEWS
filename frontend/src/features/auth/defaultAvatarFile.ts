import type { DefaultAvatar } from './defaultAvatar'

/** Save presets through the same persistent PNG upload as custom avatars. */
export async function defaultAvatarFile(avatar: DefaultAvatar): Promise<File> {
  const image = new Image()
  image.src = avatar.src
  await image.decode().catch(() => { throw new Error() })
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 256
  const context = canvas.getContext('2d')
  if (!context) throw new Error()
  context.drawImage(image, 0, 0, 256, 256)
  const png = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error()), 'image/png')
  })
  return new File([png], `avatar-${avatar.id}.png`, { type: 'image/png' })
}
