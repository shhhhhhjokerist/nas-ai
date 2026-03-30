<template>
  <div class="login-view">
    <h1>Login</h1>
    <LoginForm />
  </div>
</template>

<script>
import LoginForm from '../components/LoginForm.vue';

export default {
  name: 'LoginView',
  components: {
    LoginForm
  }
}
</script>

<style scoped>
.login-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100vh;
}
</style>