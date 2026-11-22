// Preferências deste navegador (não vão para a API): último usuário que entrou e velocidade do orbe. Sempre com try/catch: o armazenamento pode estar bloqueado.
import { useCallback, useState } from "react";

const KEYS = {
  lastUser: "sona_last_user",
  orbSpeed: "sona_orb_speed",
} as const;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // armazenamento indisponível: vale só nesta aba
  }
}

export interface LastUser {
  name: string;
  email: string;
}

export const getLastUser = () => read<LastUser | null>(KEYS.lastUser, null);
export const setLastUser = (u: LastUser) => write(KEYS.lastUser, u);

function usePref<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback));
  const set = useCallback(
    (v: T) => {
      setValue(v);
      write(key, v);
    },
    [key],
  );
  return [value, set];
}

export const useOrbSpeed = () => usePref<number>(KEYS.orbSpeed, 1);
