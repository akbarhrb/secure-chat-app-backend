import axios from 'axios';

axios.get('http://192.168.1.100:8000/users')
  .then(res => console.log(res.data))
  .catch(err => console.log(err));
