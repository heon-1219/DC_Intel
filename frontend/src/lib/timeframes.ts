import type { Lang, Timeframe } from "../api/types";

/** Localized timeframe labels (ui-ux §7.4.3). */
export const TF_LABEL: Record<Lang, Record<Timeframe, string>> = {
  en: { "1h": "1h", "5h": "5h", "24h": "24h", "2d": "2d", "3d": "3d", "5d": "5d" },
  ko: { "1h": "1시간", "5h": "5시간", "24h": "24시간", "2d": "2일", "3d": "3일", "5d": "5일" },
};
