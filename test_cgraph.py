from pydaograph import GPipeline




def main():
    pipeline = GPipeline()
    a = pipeline.buildFromJson("/Users/xiechuxi/Desktop/codes/meta_agent/example.json")
    print("Pipeline built from JSON:", a.getInfo())
    pipeline.process()
    pipeline.destroy()


if __name__ == "__main__":
    main()




