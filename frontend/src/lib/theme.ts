// Tema claro/escuro da aplicação inteira. A classe `dark` no <html> liga o tema escuro; sem ela,
// o CSS troca a paleta para a clara (ver index.css). O index.html aplica o tema antes de desenhar
// a página, para não piscar; aqui ficam a troca e a escolha salva neste navegador.
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "sona_theme";
const listeners = new Set<() => void>();

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // armazenamento bloqueado: o tema vale só nesta aba
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, current, () => "dark" as Theme);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")];
}
