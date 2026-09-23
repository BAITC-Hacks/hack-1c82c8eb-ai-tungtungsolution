import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CareerData, UploadFiles } from "./types";

export function useEmployees(data: CareerData) {
  return useQuery({ queryKey: ["employees"], queryFn: () => data.employees() });
}
export function useProfile(data: CareerData, id: string) {
  return useQuery({
    queryKey: ["profile", id],
    queryFn: () => data.profile(id),
  });
}
export function useRecommendations(
  data: CareerData,
  id: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["recommendations", id],
    queryFn: () => data.recommendations(id),
    enabled,
    staleTime: Infinity,
  });
}
export function useActivity(data: CareerData, id: string) {
  const client = useQueryClient();
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["profile", id] }),
      client.invalidateQueries({ queryKey: ["recommendations", id] }),
      client.invalidateQueries({ queryKey: ["overview"] }),
      client.invalidateQueries({ queryKey: ["audit"] }),
    ]);
  };
  return {
    complete: useMutation({
      mutationFn: (eventId: string) => data.complete(id, eventId),
      onSuccess: invalidate,
    }),
    dismiss: useMutation({
      mutationFn: (eventId: string) => data.dismiss(id, eventId),
      onSuccess: invalidate,
    }),
  };
}
export function useOverview(data: CareerData) {
  return useQuery({ queryKey: ["overview"], queryFn: () => data.overview() });
}
export function useAudit(data: CareerData) {
  return useQuery({ queryKey: ["audit"], queryFn: () => data.audit() });
}
export function useUpload(data: CareerData) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (files: UploadFiles) => data.upload(files),
    onSuccess: () => client.invalidateQueries(),
  });
}
