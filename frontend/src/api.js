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

export default http
