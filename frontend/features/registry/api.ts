/* The Registry's paged list, read from the browser as the person scrolls or filters. */

import type { RegistryPage } from "@/lib/api";
import { call } from "@/features/ask/lib/rest";

export const fetchRegistryPage = (query: string) => call<RegistryPage>(`/api/registry?${query}`);
