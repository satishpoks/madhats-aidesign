import '@testing-library/jest-dom'

// Stub browser APIs that jsdom does not implement
if (typeof URL.createObjectURL === 'undefined') {
  URL.createObjectURL = () => 'mock-blob-url'
}
if (typeof URL.revokeObjectURL === 'undefined') {
  URL.revokeObjectURL = () => {}
}
