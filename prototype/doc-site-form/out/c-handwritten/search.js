
(function(){
  var q=document.getElementById('q'),hits=document.getElementById('hits'),root=document.body.dataset.root;
  function esc(s){return s.replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
  q.addEventListener('input',function(){
    var t=q.value.trim().toLowerCase();hits.innerHTML='';
    if(!t){hits.style.display='none';return}
    var n=0;
    window.SEARCH.forEach(function(d){
      var i=d.text.toLowerCase().indexOf(t),inTitle=d.title.toLowerCase().indexOf(t)>=0;
      if(i<0&&!inTitle)return;
      if(++n>30)return;
      var s=i<0?'':esc(d.text.slice(Math.max(0,i-30),i))+'<b>'+esc(d.text.substr(i,t.length))+'</b>'+esc(d.text.substr(i+t.length,50));
      var a=document.createElement('a');a.href=root+d.url;a.innerHTML=esc(d.title)+'<br><small>'+s+'</small>';hits.appendChild(a);
    });
    if(!n)hits.innerHTML='<a>无结果</a>';
    hits.style.display='block';
  });
  document.addEventListener('click',function(e){if(e.target!==q)hits.style.display='none'});
})();
