const { defineConfig } = require('@vue/cli-service')

module.exports = defineConfig({
  transpileDependencies: true,
  lintOnSave: false,
  devServer: {
    port: 8080,
    client: {
      overlay: {
        runtimeErrors: (error) => {
          const message = (error && error.message) || ''
          if (message.indexOf('ResizeObserver loop') !== -1) return false
          return true
        },
      },
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 600000,
        proxyTimeout: 600000,
      },
    },
  },
  chainWebpack: (config) => {
    config.plugin('html').tap((args) => {
      args[0].title = '电子元件库'
      return args
    })
  },
})
