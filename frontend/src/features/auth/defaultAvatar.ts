import robot from '@/assets/avatars/robot.svg'
import cat from '@/assets/avatars/cat.svg'
import bear from '@/assets/avatars/bear.svg'
import rabbit from '@/assets/avatars/rabbit.svg'
import fox from '@/assets/avatars/fox.svg'
import owl from '@/assets/avatars/owl.svg'

const avatars = [robot, cat, bear, rabbit, fox, owl]

/** Keep each account's avatar stable across reloads and profile name changes. */
export function defaultAvatarFor(seed?: string | number | null): string {
  let hash = 0
  for (const character of String(seed ?? '').trim()) {
    hash = (Math.imul(hash, 31) + character.codePointAt(0)!) >>> 0
  }
  return avatars[hash % avatars.length] ?? robot
}
