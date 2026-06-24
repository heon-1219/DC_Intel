import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

/** Latest AIWCE whisper-EPS corroboration for a stock. The whisper job runs daily, so the value
 *  changes at most once a day — a long staleTime + no polling (the dashboard widgets poll; this is a
 *  slow daily signal). `retry: false` mirrors the prediction query so honest errors surface fast. */
const ONE_HOUR = 60 * 60 * 1000;

export function useWhisper(instrument: string) {
  return useQuery({
    queryKey: ["whisper", instrument],
    queryFn: ({ signal }) => api.whisper(instrument, signal),
    staleTime: 6 * ONE_HOUR,
    gcTime: 12 * ONE_HOUR,
    retry: false,
  });
}
