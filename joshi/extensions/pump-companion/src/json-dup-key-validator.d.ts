declare module "json-dup-key-validator" {
  export function validate(jsonString: string, allowDuplicatedKeys?: boolean): string | undefined;
}
