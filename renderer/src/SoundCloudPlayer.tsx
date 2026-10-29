import { forwardRef, useLayoutEffect, useImperativeHandle, useRef } from 'react';
import './vendor/soundcloud-widget.js';
export type CloudControls={play:()=>void;pause:()=>void;seek:(seconds:number)=>void};
type Props={url:string;onPlaying:(playing:boolean)=>void;onPosition:(seconds:number)=>void;onDuration:(seconds:number)=>void;onEnd:()=>void;onError:()=>void};
export const SoundCloudPlayer=forwardRef<CloudControls,Props>(function SoundCloudPlayer(props,ref){
  const frame=useRef<HTMLIFrameElement>(null);const widget=useRef<any>(null);const ready=useRef(false);const wanted=useRef(true);const callbacks=useRef(props);callbacks.current=props;
  useImperativeHandle(ref,()=>({play(){wanted.current=true;if(ready.current)widget.current?.play();},pause(){wanted.current=false;widget.current?.pause();},seek(seconds){if(ready.current)widget.current?.seekTo(seconds*1000);}}),[]);
  useLayoutEffect(()=>{
    const api=(window as any).SC.Widget;const instance=api(frame.current!);widget.current=instance;let alive=true;
    const timer=setTimeout(()=>{if(alive&&!ready.current)callbacks.current.onError();},25000);
    const bind=(name:string,fn:(event?:any)=>void)=>instance.bind(name,(event:any)=>{if(alive)fn(event);});
    bind(api.Events.READY,()=>{clearTimeout(timer);ready.current=true;instance.getDuration((ms:number)=>{if(alive)callbacks.current.onDuration(ms/1000);});if(wanted.current)instance.play();});
    bind(api.Events.PLAY,()=>callbacks.current.onPlaying(true));bind(api.Events.PAUSE,()=>callbacks.current.onPlaying(false));
    bind(api.Events.PLAY_PROGRESS,event=>callbacks.current.onPosition((event?.currentPosition||0)/1000));
    bind(api.Events.SEEK,event=>callbacks.current.onPosition((event?.currentPosition||0)/1000));
    bind(api.Events.FINISH,()=>callbacks.current.onEnd());bind(api.Events.ERROR,()=>callbacks.current.onError());
    // The Widget API dereferences iframe.contentWindow. Tear down before React
    // removes the iframe, otherwise the SDK throws during passive cleanup.
    return()=>{alive=false;ready.current=false;clearTimeout(timer);instance.pause();for(const name of Object.values(api.Events))instance.unbind(name);widget.current=null;};
  },[]);
  const src='https://w.soundcloud.com/player/?'+new URLSearchParams({url:props.url,auto_play:'false',show_artwork:'false',show_comments:'false',show_user:'true',visual:'false',color:'#b63339'});
  return <iframe ref={frame} className="soundcloud-frame" title="SoundCloud official player" src={src} allow="autoplay" sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer"/>;
});
