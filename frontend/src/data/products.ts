export type CapStyle = 'snapback' | 'trucker' | 'bucket' | 'beanie' | 'visor'
export type DecorationStyle = 'embroidery' | 'print'
export type PlacementZone = 'auto' | 'front' | 'side' | 'back' | 'under-brim'

export interface ColourSwatch {
  name: string
  hex: string
}

export interface Product {
  id: string
  name: string
  brand: string
  style: CapStyle
  swatches: ColourSwatch[]
  defaultColour: string
  placementZones: PlacementZone[]
  decorationTypes: DecorationStyle[]
}

export const PRODUCTS: Product[] = [
  {
    id: 'p1',
    name: 'Classic Snapback',
    brand: 'Otto',
    style: 'snapback',
    swatches: [
      { name: 'Black', hex: '#111111' },
      { name: 'Navy', hex: '#1B2A4A' },
      { name: 'White', hex: '#F0F0F0' },
      { name: 'Forest', hex: '#2D4A2D' },
    ],
    defaultColour: '#111111',
    placementZones: ['front', 'side', 'back'],
    decorationTypes: ['embroidery', 'print'],
  },
  {
    id: 'p2',
    name: 'Pro Trucker',
    brand: 'Richardson',
    style: 'trucker',
    swatches: [
      { name: 'Black/White', hex: '#111111' },
      { name: 'Navy/White', hex: '#1B2A4A' },
      { name: 'Khaki/Brown', hex: '#C4A882' },
      { name: 'Red/White', hex: '#CC2200' },
    ],
    defaultColour: '#111111',
    placementZones: ['front', 'side'],
    decorationTypes: ['embroidery', 'print'],
  },
  {
    id: 'p3',
    name: 'Bucket Hat',
    brand: 'Inivi',
    style: 'bucket',
    swatches: [
      { name: 'White', hex: '#F0F0F0' },
      { name: 'Black', hex: '#111111' },
      { name: 'Sand', hex: '#D4B896' },
      { name: 'Olive', hex: '#6B7A3B' },
    ],
    defaultColour: '#F0F0F0',
    placementZones: ['front', 'side', 'back', 'under-brim'],
    decorationTypes: ['embroidery', 'print'],
  },
  {
    id: 'p4',
    name: 'Cuffed Beanie',
    brand: 'GTO',
    style: 'beanie',
    swatches: [
      { name: 'Charcoal', hex: '#3A3A3A' },
      { name: 'Black', hex: '#111111' },
      { name: 'Navy', hex: '#1B2A4A' },
      { name: 'Red', hex: '#CC2200' },
    ],
    defaultColour: '#3A3A3A',
    placementZones: ['front', 'side'],
    decorationTypes: ['embroidery'],
  },
  {
    id: 'p5',
    name: 'Sport Visor',
    brand: 'FlexFit',
    style: 'visor',
    swatches: [
      { name: 'Black', hex: '#111111' },
      { name: 'White', hex: '#F0F0F0' },
      { name: 'Navy', hex: '#1B2A4A' },
    ],
    defaultColour: '#111111',
    placementZones: ['front'],
    decorationTypes: ['embroidery', 'print'],
  },
  {
    id: 'p6',
    name: 'Heritage Snapback',
    brand: 'Richardson',
    style: 'snapback',
    swatches: [
      { name: 'Olive', hex: '#6B7A3B' },
      { name: 'Tan', hex: '#C4A882' },
      { name: 'Slate', hex: '#4A5568' },
      { name: 'Burgundy', hex: '#6B1F2A' },
    ],
    defaultColour: '#6B7A3B',
    placementZones: ['front', 'side', 'back'],
    decorationTypes: ['embroidery', 'print'],
  },
]
