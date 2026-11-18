declare module '*.css' {}

interface ImportMeta {
  readonly glob: (pattern: string, options?: { eager?: boolean; query?: string; import?: string }) => Record<string, any>;
}
