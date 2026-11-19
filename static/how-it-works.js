"use strict";
const themeButton=document.getElementById('theme-toggle');
function setHelpTheme(theme){
  document.documentElement.dataset.theme=theme;
  themeButton.setAttribute('aria-pressed',String(theme==='dark'));
  themeButton.textContent=theme==='dark'?'Light mode':'Dark mode';
}
let helpTheme=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
try{const saved=JSON.parse(localStorage.getItem('portfolio-theme'));if(saved==='dark'||saved==='light')helpTheme=saved;}catch{}
setHelpTheme(helpTheme);
themeButton.addEventListener('click',()=>{
  helpTheme=document.documentElement.dataset.theme==='dark'?'light':'dark';
  setHelpTheme(helpTheme);
  try{localStorage.setItem('portfolio-theme',JSON.stringify(helpTheme));}catch{}
});
