# DISMEPE ONE — Android instalavel (Expo + FCM nativo)

Codigo-fonte do aplicativo Android que abre https://dismepeone.com.br/ em WebView nativa; nao e PWA. Identificador: `br.com.dismepe.dismepeone`. Projeto Expo: conta `dantonmelo`.

## Estado atual

O cliente solicita permissao de notificacoes, obtem token FCM nativo e tenta registrar o dispositivo em `POST /mobile/push/register`. **A API de cadastro, armazenamento por usuario, revogacao em logout, central de avisos e envio pelo Firebase ainda nao estao implementados no servidor**. Portanto, nao afirmar que as notificacoes ja funcionam, mesmo que um APK compile. O APK tambem nao foi gerado ou testado em aparelho.

Este codigo fica em uma branch separada, sem alterar a branch main nem provocar deploy do portal.

## Firebase e seguranca

O repositorio original e PUBLICO. Nao publicar chaves privadas da conta de servico, segredos de Render, tokens Expo nem arquivo `firebase-service-account*.json`. A configuracao cliente `google-services.json` foi deliberadamente excluida do GitHub. O arquivo cliente original permanece com o proprietario.

Para compilar via EAS, no projeto Expo crie uma variavel de ambiente de tipo **file** chamada `GOOGLE_SERVICES_JSON` contendo apenas o `google-services.json` CLIENTE do Android. Em `app.config.js` a opcao `android.googleServicesFile` usa o caminho desse arquivo no ambiente EAS. Nunca use o JSON de conta de servico nessa variavel.

## Vincular projeto Expo / compilar

1. Conectar a conta Expo `dantonmelo` ao GitHub, selecionando a branch `feature/dismepe-one-android-expo-fcm` e a pasta do projeto `mobile/android`, quando essas opcoes aparecerem na plataforma. Isso requer autorizacao do proprietario na Expo; uma publicacao no GitHub nao inicia automaticamente o build.
2. Criar/vincular o projeto Expo DISMEPE ONE Mobile e registrar o `extra.eas.projectId` na configuracao do app, se solicitado pela plataforma.
3. Configurar a variavel EAS `GOOGLE_SERVICES_JSON` (tipo file, ambiente associado ao build preview), com o arquivo cliente do Firebase para `br.com.dismepe.dismepeone`.
4. Build Android usando o perfil `preview` definido em `eas.json` (distribution internal / buildType apk). A assinatura Android deve ser criada/gerenciada em local seguro pela conta do proprietario.
5. Antes de distribuir o APK a equipe, implementar o backend autenticado, testar cadastro/revogacao dos tokens e comprovar push com o aplicativo fechado no aparelho Android.

Se for utilizar terminal local: `npm install`, `npx expo install --fix`, `npx eas-cli@latest login`, `npx eas-cli@latest init`, `npx eas-cli@latest build --platform android --profile preview`, apos configurar o arquivo cliente local ou no EAS.

A instalacao via GitHub so publica **codigo**, nao um APK pronto nem uma notificacao funcional.
