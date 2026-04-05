declare module "@tanstack/react-query" {
  import type { ComponentType, ReactNode } from "react";

  export type QueryKey = readonly unknown[];

  export interface UseQueryOptions<TData = unknown> {
    queryKey: QueryKey;
    queryFn: () => Promise<TData> | TData;
    enabled?: boolean;
    staleTime?: number;
    refetchInterval?: number | false | (() => number | false);
    refetchOnWindowFocus?: boolean;
  }

  export interface UseQueryResult<TData = unknown> {
    data: TData | undefined;
    isLoading: boolean;
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    refetch: () => Promise<unknown>;
  }

  export function useQuery<TData = unknown>(options: UseQueryOptions<TData>): UseQueryResult<TData>;

  export class QueryClient {
    constructor(config?: unknown);
    invalidateQueries(filters?: { queryKey?: QueryKey }): Promise<void>;
    setQueryData<TData = unknown>(
      queryKey: QueryKey,
      updater: TData | ((oldData: TData | undefined) => TData | undefined),
    ): void;
  }

  export const QueryClientProvider: ComponentType<{
    client: QueryClient;
    children?: ReactNode;
  }>;

  export function useQueryClient(): QueryClient;
}
