// Light / dark / system theme. "system" follows the OS; an explicit choice is remembered per browser.
import { useCallback, useEffect, useState } from 'react'

export type ThemeChoice = 'system' | 'light' | 'dark'
const KEY = 'ss-theme'
const ORDER: ThemeChoice[] = ['system', 'light', 'dark']

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
  try {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

export function useTheme(): { choice: ThemeChoice; cycle: () => void } {
  const [choice, setChoice] = useState<ThemeChoice>(readChoice)
  useEffect(() => applyTheme(choice), [choice])
  const cycle = useCallback(() => setChoice((c) => ORDER[(ORDER.indexOf(c) + 1) % ORDER.length]), [])
  return { choice, cycle }
}
