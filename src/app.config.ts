export default defineAppConfig({
  pages: [
    'pages/login/index',
    'pages/profile/index',
    'pages/workbench/index',
    'pages/before-photos/index',
    'pages/after-photos/index',
    'pages/voice/index',
    'pages/report/index',
    'pages/customer-acceptance/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#173b65',
    navigationBarTitleText: '干完了',
    navigationBarTextStyle: 'white',
    backgroundColor: '#f5f7fa'
  },
  permission: {
    'scope.userLocation': {
      desc: '用于在地图中选择并记录上门服务地址'
    }
  },
  requiredPrivateInfos: ['chooseLocation']
})
