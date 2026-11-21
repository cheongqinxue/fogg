export interface SlashField {
  id: string;
  label: string;
  masked?: boolean;
}

export interface SlashColumn {
  id: string;
  value: (item: SlashItem) => string | undefined;
  width?: string;
}

export interface SlashItem {
  id: string;
  title: string;
  description?: string;
  trailing?: string;
  indicator?: { kind: "status" | "checkbox"; active: boolean };
  children?: SlashItem[];
  columns?: SlashColumn[];
  fields?: SlashField[];
  disabled?: boolean;
  action?: () => void;
  onToggle?: (checked: boolean) => void | Promise<void>;
  onSubmit?: (values: Record<string, string>) => void | Promise<void>;
}
