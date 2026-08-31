/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

import 'axios'

declare module 'axios' {
  // Keep the generic parameter aligned with Axios' request config declaration.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars
  interface InternalAxiosRequestConfig<D = any> {
    __authToken?: string | null
  }
}
