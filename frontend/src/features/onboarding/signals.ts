import { ref } from 'vue'

// Shared with the layout so scrolling a highlighted target cannot hide the dock.
export const tourActive = ref(false)
export const tourRequest = ref(0)
export const requestTour = () => { tourRequest.value += 1 }
