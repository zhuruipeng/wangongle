export const serviceOrder = {
  orderNo: 'FW20260718001', customer: '王先生', phone: '138****6688',
  address: '临沂市兰山区金雀山路', service: '1.5匹壁挂空调安装', status: '待施工'
}

export const recognitionExample = '完成空调安装，使用两米铜管和一个不锈钢支架，抽真空十五分钟，试机正常。'

export const initialReport = {
  completed: ['已完成1.5匹壁挂空调安装', '已完成抽真空和试机', '制冷运行正常'],
  materials: [
    { name: '铜管', quantity: '2米', price: '160' },
    { name: '不锈钢支架', quantity: '1套', price: '80' }
  ],
  serviceFee: '150', materialFee: '240', paid: '0',
  risks: ['室外机安装位置较高', '已提醒客户注意定期清洗'],
  afterSales: '建议12个月后清洗保养'
}
