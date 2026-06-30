// Backend DTO mirrors — keep in sync with FastAPI schemas

export interface Product {
  id: string
  style: string
  colour: string
  name: string
  description?: string
  store_url?: string
  reference_image_url: string
  view_images: Record<string, string>
  placement_zones: string[]
  decoration_types: string[]
}

export interface ProductPage {
  items: Product[]
  total: number
  limit: number
  offset: number
}

export interface CreateSessionResponse {
  session_id: string
  share_token: string
  state: string
}

export interface ChatResponse {
  reply: string
  state: string
  data: Record<string, unknown>
}

export interface GenerationStatus {
  status: string
  image_url: string
  watermarked_url: string
}
