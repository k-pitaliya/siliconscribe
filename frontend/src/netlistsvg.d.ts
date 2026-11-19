declare module 'netlistsvg' {
  /** Lays out a Yosys JSON netlist with ELK and draws it with the given SVG skin. */
  export function render(skin: string, netlist: unknown): Promise<string | undefined>
}
