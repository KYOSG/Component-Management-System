import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail
    let message = ''
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail) && detail[0]?.msg) {
      message = detail[0].msg
    }
    if (error.response?.status !== 401 && message) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export function reportRequestError(error) {
  // 页面事件里如果继续抛出，开发服务器会盖住全屏，导致无法点击。
  if (!axios.isAxiosError(error)) {
    console.error(error)
    return
  }
  if (!error.response) ElMessage.error('无法连接服务器')
}

export default http
